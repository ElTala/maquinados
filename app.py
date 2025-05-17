from flask import Flask, render_template, request, url_for, redirect, session, flash, send_from_directory
from flask_socketio import SocketIO, emit
import base64, io, re, json, os, uuid
from PyPDF2 import PdfReader
from cryptography.fernet import Fernet

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

UPLOAD_PDF = os.path.join('static', 'uploads', 'pdf')
os.makedirs(UPLOAD_PDF, exist_ok=True)

BASE_PROY = 'bases/proyectos.json'
BASE_MAQ = 'bases/maquinados.json'
BASE_USERS = 'bases/usuarios.json'
USER_FILES_DIR = os.path.join('bases', 'archivos')

def load_users():
    try:
        with open(BASE_USERS, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_users(users):
    with open(BASE_USERS, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def encrypt_pwd(plain):
    return fernet.encrypt(plain.encode()).decode()

def decrypt_pwd(token):
    return fernet.decrypt(token.encode()).decode()

KEY_FILE = 'secret.key'
if os.path.exists(KEY_FILE):
    key = open(KEY_FILE, 'rb').read()
else:
    key = Fernet.generate_key()
    open(KEY_FILE, 'wb').write(key)
fernet = Fernet(key)

os.makedirs(USER_FILES_DIR, exist_ok=True)

@app.context_processor
def inject_user():
    users = load_users()
    u = next((x for x in users if x['id'] == session.get('user_id')), None)
    return dict(u=u)

@app.route('/')
def index():
    with open(BASE_PROY, encoding='utf-8') as f:
        proyectos = json.load(f)
    return render_template('index.html', proyectos=proyectos)

@app.route('/nuevoProyecto')
def nuevoproyecto():
    with open(BASE_PROY, encoding='utf-8') as f:
        proyectos = json.load(f)
    return render_template('nuevoProyecto.html', proyectos=proyectos)

@app.route('/pedidos')
def dashboard():
    with open(BASE_PROY, encoding='utf-8') as f:
        proyectos = json.load(f)
    try:
        with open(BASE_MAQ, encoding='utf-8') as f:
            maquinados = json.load(f)
    except FileNotFoundError:
        maquinados = []
    grouped = {}
    for m in maquinados:
        grouped.setdefault(m['proyecto'], []).append(m)
    return render_template('pedidos.html', proyectos=proyectos, grouped_maquinados=grouped)

@socketio.on('upload_pdf')
def handle_pdf(data):
    binary = base64.b64decode(data['content'])
    path = os.path.join(UPLOAD_PDF, data['filename'])
    with open(path, 'wb') as f:
        f.write(binary)
    reader = PdfReader(io.BytesIO(binary))
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    dtm = re.search(r'(DTM[^\n]*)', text, re.I)
    desc = re.search(r'STATION NAME:[^\n]*\n([^\n]*)', text, re.I)
    emit('pdf_data', {
        'id': data['id'],
        'filename': data['filename'],
        'dtm': dtm.group(1).strip() if dtm else '',
        'descripcion': desc.group(1).strip() if desc else ''
    }, room=request.sid)

@socketio.on('new_maquinado')
def handle_new_maquinado(data):
    try:
        with open(BASE_MAQ, encoding='utf-8') as f:
            maqs = json.load(f)
    except FileNotFoundError:
        maqs = []
    maqs.append(data)
    with open(BASE_MAQ, 'w', encoding='utf-8') as f:
        json.dump(maqs, f, ensure_ascii=False, indent=4)
    emit('receive_maquinado', data, broadcast=True)

@app.route('/registrar', methods=['GET', 'POST'])
def registrar():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        pwd = request.form['password']
        pwd2 = request.form['password2']
        if pwd != pwd2:
            flash('Las contraseñas no coinciden', 'error')
            return redirect(url_for('registrar'))
        users = load_users()
        if any(u['email'] == email for u in users):
            flash('Ese correo ya está registrado', 'error')
            return redirect(url_for('registrar'))
        next_id = max([u['id'] for u in users], default=0) + 1
        users.append({
            'id': next_id,
            'username': username,
            'email': email,
            'password': encrypt_pwd(pwd),
            'profile_pic': None
        })
        save_users(users)
        session['user_id'] = next_id
        return redirect(url_for('index'))
    return render_template('registrar.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        pwd = request.form['password']
        users = load_users()
        user = next((u for u in users if u['email'] == email), None)
        if not user or decrypt_pwd(user['password']) != pwd:
            flash('Usuario o contraseña inválidos', 'error')
            return redirect(url_for('login'))
        session['user_id'] = user['id']
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/recuperar', methods=['GET', 'POST'])
def olvido():
    recovered = None
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        users = load_users()
        user = next((u for u in users if u['email'] == email), None)
        if user:
            recovered = decrypt_pwd(user['password'])
        else:
            flash('Correo no registrado', 'error')
    return render_template('olvido.html', recovered=recovered)

@app.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    users = load_users()
    user = next((u for u in users if u['id'] == session['user_id']), None)
    if not user:
        session.pop('user_id')
        return redirect(url_for('login'))
    if request.method == 'POST':
        user['username'] = request.form['username'].strip()
        user['email'] = request.form['email'].strip().lower()
        if request.form.get('password'):
            user['password'] = encrypt_pwd(request.form['password'])
        pic = request.files.get('profile_pic')
        if pic and pic.filename:
            fn = f"user_{user['id']}_{uuid.uuid4().hex}{os.path.splitext(pic.filename)[1]}"
            path = os.path.join(USER_FILES_DIR, fn)
            pic.save(path)
            user['profile_pic'] = fn
        save_users(users)
        flash('Perfil actualizado', 'success')
        return redirect(url_for('perfil'))
    return render_template('perfil.html', user=user)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/archivos/<path:filename>')
def archivos(filename):
    return send_from_directory(USER_FILES_DIR, filename)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
