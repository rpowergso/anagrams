from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_session import Session
import requests
from game import check_dictionary, generate_tiles, same_root

app = Flask(__name__)
app.secret_key = 'something'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

@app.route('/')
def home():
    return redirect(url_for('index'))

@app.route('/homepage', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        difficulty = request.form['difficulty']
        session['difficulty'] = difficulty
        return redirect(url_for('game'))
    return render_template('homepage.html')

@app.route('/gamescreen')
def game():
    difficulty = session.get('difficulty', 'easy')
    return render_template('gamescreen.html', difficulty=difficulty)

@app.route('/get-tile')
def get_tile():
    if 'tiles' not in session:
        tiles = generate_tiles()
        session['tiles'] = tiles
        session.modified = True
    tiles = session['tiles']
    if not tiles:
        return jsonify({'tile': None, 'done': True})
    tile = tiles.pop(0)
    session['tiles'] = tiles
    session.modified = True
    return jsonify({'tile': tile, 'done': False})

@app.route('/check-word', methods=['POST'])
def check_word():
    word = request.json.get('word', '').lower().strip()
    valid = check_dictionary(word)
    return jsonify({'valid': valid})

@app.route('/check-stem', methods=['POST'])
def check_stem():
    word1 = request.json.get('word1', '').lower()
    word2 = request.json.get('word2', '').lower()
    return jsonify({'same_root': same_root(word1, word2)})

if __name__ == '__main__':
    app.run(debug=True)