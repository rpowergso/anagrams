import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for

profile = Blueprint('profile', __name__)
EVENT_ID = re.compile(r'[a-f0-9]{32}')
WORD = re.compile(r'[A-Z]{3,30}')
RESULTS = {'game', 'win', 'puzzle', 'solve'}


def init_profile(app):
    profile_db = os.environ.get('PROFILE_DB_PATH')
    app.config['PROFILE_DB_PATH'] = profile_db
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    callback = os.environ.get('GOOGLE_REDIRECT_URI')
    if client_id and client_secret and callback and profile_db:
        from authlib.integrations.flask_client import OAuth

        oauth = OAuth(app)
        app.extensions['profile_google'] = oauth.register(
            'google',
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid profile', 'code_challenge_method': 'S256'},
        )
        app.config['GOOGLE_REDIRECT_URI'] = callback
    app.register_blueprint(profile)


@profile.app_context_processor
def profile_context():
    return {
        'profile_user': session.get('profile_user'),
        'profile_google_enabled': 'profile_google' in current_app.extensions,
    }


@profile.get('/stats')
def stats_page():
    return render_template('stats.html')


@profile.get('/profile/google')
def google_login():
    google = current_app.extensions.get('profile_google')
    if not google:
        abort(503)
    return google.authorize_redirect(current_app.config['GOOGLE_REDIRECT_URI'])


@profile.get('/profile/google/callback')
def google_callback():
    google = current_app.extensions.get('profile_google')
    if not google:
        abort(503)

    from authlib.integrations.base_client import OAuthError
    from requests import RequestException

    try:
        identity = google.authorize_access_token().get('userinfo') or {}
        subject = identity.get('sub')
    except (OAuthError, RequestException, ValueError):
        subject = None
    if not subject:
        return render_template('stats.html', sign_in_error=True), 400
    session['profile_user'] = {'id': subject, 'name': identity.get('given_name') or 'Player'}
    current_app.session_interface.regenerate(session)
    return redirect(url_for('profile.stats_page'))


@profile.post('/profile/sign-out')
def sign_out():
    # A cross-origin form must never be able to change the active profile.
    token = session.get('profile_logout_token')
    if not session.get('profile_user') or not token or request.form.get('token') != token:
        abort(403)
    session.pop('profile_user')
    session.pop('profile_logout_token')
    return redirect(url_for('index'))


@profile.app_context_processor
def logout_context():
    def logout_token():
        if 'profile_logout_token' not in session:
            session['profile_logout_token'] = secrets.token_urlsafe(32)
        return session['profile_logout_token']

    return {'profile_logout_token': logout_token}


def save_and_read_stats(user_id, events):
    totals = {'letters': {}, 'words': 0, 'games': 0, 'wins': 0, 'puzzles': 0, 'solved': 0}
    path = Path(current_app.config['PROFILE_DB_PATH'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS profile_stats (user_id TEXT PRIMARY KEY, totals TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS profile_events (id TEXT PRIMARY KEY)')
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT totals FROM profile_stats WHERE user_id = ?', (user_id,)).fetchone()
        if previous:
            totals = json.loads(previous[0])
        for event in events:
            inserted = db.execute('INSERT OR IGNORE INTO profile_events VALUES (?)', (event['id'],))
            if not inserted.rowcount:
                continue
            word = event.get('word', '')
            if word:
                totals['words'] += 1
            for letter in word:
                totals['letters'][letter] = totals['letters'].get(letter, 0) + 1
            result = event.get('result')
            totals['games'] += result in ('game', 'win')
            totals['wins'] += result == 'win'
            totals['puzzles'] += result in ('puzzle', 'solve')
            totals['solved'] += result == 'solve'
        if events:
            db.execute('INSERT OR REPLACE INTO profile_stats VALUES (?, ?)', (user_id, json.dumps(totals)))
    return totals


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


@profile.route('/api/profile/stats', methods=['GET', 'POST'])
def sync_stats():
    user = session.get('profile_user')
    if not user or not current_app.config['PROFILE_DB_PATH']:
        abort(401)
    events = request.get_json(silent=True) if request.method == 'POST' else []
    if not isinstance(events, list) or len(events) > 100 or not all(map(valid_event, events)):
        return jsonify(error='Invalid stats batch.'), 400
    response = jsonify(save_and_read_stats(user['id'], events))
    response.headers['Cache-Control'] = 'no-store'
    return response
