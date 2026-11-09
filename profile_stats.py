import json
import os
import re
import secrets
import threading
import time

import requests
from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for

profile = Blueprint('profile', __name__)
EVENT_ID = re.compile(r'[a-f0-9]{32}')
WORD = re.compile(r'[A-Z]{3,30}')
RESULTS = {'game', 'win', 'puzzle', 'solve'}
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.appdata'
DRIVE_FILES = 'https://www.googleapis.com/drive/v3/files'
DRIVE_UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
PROFILE_FILE = 'anagrams-letter-stats-v1.json'
profile_locks = tuple(threading.Lock() for _ in range(64))


def init_profile(app):
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    callback = os.environ.get('GOOGLE_REDIRECT_URI')
    if client_id and client_secret and callback:
        from authlib.integrations.flask_client import OAuth

        oauth = OAuth(app)
        app.extensions['profile_google'] = oauth.register(
            'google',
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': f'openid profile {DRIVE_SCOPE}', 'code_challenge_method': 'S256'},
        )
        app.config['GOOGLE_REDIRECT_URI'] = callback
    app.register_blueprint(profile)


def profile_logout_token():
    if 'profile_logout_token' not in session:
        session['profile_logout_token'] = secrets.token_urlsafe(32)
    return session['profile_logout_token']


@profile.app_context_processor
def profile_context():
    return {
        'profile_user': session.get('profile_user'),
        'profile_google_enabled': 'profile_google' in current_app.extensions,
        'profile_logout_token': profile_logout_token,
    }


@profile.get('/stats')
def stats_page():
    return render_template('stats.html')


@profile.get('/profile/google')
def google_login():
    google = current_app.extensions.get('profile_google')
    if not google:
        abort(503)
    return google.authorize_redirect(current_app.config['GOOGLE_REDIRECT_URI'], access_type='offline')


@profile.get('/profile/google/callback')
def google_callback():
    google = current_app.extensions.get('profile_google')
    if not google:
        abort(503)

    from authlib.integrations.base_client import OAuthError

    try:
        token = google.authorize_access_token()
        identity = token.get('userinfo') or {}
        subject = identity.get('sub')
        allowed_scopes = token.get('scope', '').split()
    except (OAuthError, requests.RequestException, ValueError):
        subject = None
    if not subject or DRIVE_SCOPE not in allowed_scopes:
        return render_template('stats.html', sign_in_error=True), 400
    existing_user = session.get('profile_user') or {}
    refresh_token = token.get('refresh_token')
    if not refresh_token and existing_user.get('id') == subject:
        refresh_token = (session.get('profile_google_token') or {}).get('refresh_token')
    session['profile_user'] = {'id': subject, 'name': identity.get('given_name') or 'Player'}
    session['profile_google_token'] = {
        'access_token': token['access_token'],
        'refresh_token': refresh_token,
        'expires_at': token.get('expires_at', 0),
    }
    current_app.session_interface.regenerate(session)
    return redirect(url_for('profile.stats_page'))


@profile.post('/profile/sign-out')
def sign_out():
    token = session.get('profile_logout_token')
    if not session.get('profile_user') or not token or request.form.get('token') != token:
        abort(403)
    session.pop('profile_user')
    session.pop('profile_google_token', None)
    session.pop('profile_logout_token')
    return redirect(url_for('index'))


def drive_access_token(google):
    token = session.get('profile_google_token') or {}
    if token.get('access_token') and token.get('expires_at', 0) > time.time() + 30:
        return token['access_token']
    if not token.get('refresh_token'):
        return None
    response = requests.post('https://oauth2.googleapis.com/token', data={
        'grant_type': 'refresh_token',
        'refresh_token': token['refresh_token'],
        'client_id': google.client_id,
        'client_secret': google.client_secret,
    }, timeout=8)
    if response.status_code in (400, 401):
        return None
    response.raise_for_status()
    renewed = response.json()
    token['access_token'] = renewed['access_token']
    token['expires_at'] = int(time.time()) + renewed['expires_in']
    session['profile_google_token'] = token
    return token['access_token']


def valid_event(event):
    if not isinstance(event, dict):
        return False
    event_id = event.get('id')
    word = event.get('word', '')
    result = event.get('result', '')
    return (
        isinstance(event_id, str) and EVENT_ID.fullmatch(event_id)
        and isinstance(word, str) and (not word or WORD.fullmatch(word))
        and isinstance(result, str) and (not result or result in RESULTS)
        and (word or result)
    )


def summarize(events):
    totals = {'letters': {}, 'words': 0, 'games': 0, 'wins': 0, 'puzzles': 0, 'solved': 0}
    for word, result in events.values():
        if word:
            totals['words'] += 1
        for letter in word:
            totals['letters'][letter] = totals['letters'].get(letter, 0) + 1
        totals['games'] += result in ('game', 'win')
        totals['wins'] += result == 'win'
        totals['puzzles'] += result in ('puzzle', 'solve')
        totals['solved'] += result == 'solve'
    return totals


def save_and_read_stats(access_token, updates):
    headers = {'Authorization': f'Bearer {access_token}'}
    with requests.Session() as drive:
        drive.headers.update(headers)
        ids = []
        params = {
            'spaces': 'appDataFolder', 'q': f"name = '{PROFILE_FILE}' and trashed = false",
            'fields': 'nextPageToken,files(id)', 'orderBy': 'createdTime',
        }
        while True:
            response = drive.get(DRIVE_FILES, params=params, timeout=8)
            response.raise_for_status()
            files = response.json()
            ids.extend(file['id'] for file in files.get('files', []))
            if not files.get('nextPageToken'):
                break
            params['pageToken'] = files['nextPageToken']

        events = {}
        etag = None
        for index, file_id in enumerate(ids):
            response = drive.get(f'{DRIVE_FILES}/{file_id}', params={'alt': 'media'}, timeout=8)
            response.raise_for_status()
            if index == 0:
                etag = response.headers.get('ETag')
            events.update(response.json())
        previous_count = len(events)
        for event in updates:
            events.setdefault(event['id'], [event.get('word', ''), event.get('result', '')])
        if len(events) == previous_count:
            return summarize(events)

        body = json.dumps(events, separators=(',', ':'))
        if ids:
            upload_headers = {'Content-Type': 'application/json'}
            if etag:
                upload_headers['If-Match'] = etag
            response = drive.patch(f'{DRIVE_UPLOAD}/{ids[0]}', params={'uploadType': 'media'},
                                   data=body, headers=upload_headers, timeout=12)
        else:
            boundary = secrets.token_hex(16)
            metadata = json.dumps({'name': PROFILE_FILE, 'parents': ['appDataFolder']})
            body = (
                f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{metadata}\r\n'
                f'--{boundary}\r\nContent-Type: application/json\r\n\r\n{body}\r\n--{boundary}--\r\n'
            )
            response = drive.post(DRIVE_UPLOAD, params={'uploadType': 'multipart'}, data=body,
                                  headers={'Content-Type': f'multipart/related; boundary={boundary}'}, timeout=12)
        response.raise_for_status()
    return summarize(events)


@profile.route('/api/profile/stats', methods=['GET', 'POST'])
def sync_stats():
    user = session.get('profile_user')
    google = current_app.extensions.get('profile_google')
    if not user or not google:
        abort(401)
    events = request.get_json(silent=True) if request.method == 'POST' else []
    if not isinstance(events, list) or len(events) > 100 or not all(map(valid_event, events)):
        return jsonify(error='Invalid stats batch.'), 400
    try:
        with profile_locks[hash(user['id']) % len(profile_locks)]:
            access_token = drive_access_token(google)
            if not access_token:
                return jsonify(error='Google sign-in expired. Sign in again to sync your stats.'), 401
            response = jsonify(save_and_read_stats(access_token, events))
    except (requests.RequestException, ValueError, KeyError):
        return jsonify(error='Google stats storage is temporarily unavailable.'), 503
    response.headers['Cache-Control'] = 'no-store'
    return response
