from flask import (Flask, render_template, request, url_for, redirect,session, flash, send_from_directory)
from flask_socketio import SocketIO, emit
import base64, io, re, json, os, uuid
from PyPDF2 import PdfReader
from cryptography.fernet import Fernet
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

UPLOAD_PDF  = os.path.join('static', 'uploads', 'pdf')
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
    # agrupar por proyecto
    grouped = {}
    for m in maquinados:
        grouped.setdefault(m['proyecto'], []).append(m)
    return render_template('pedidos.html',
                           proyectos=proyectos,
                           grouped_maquinados=grouped)

@socketio.on('upload_pdf')
def handle_pdf(data):
    # guardar PDF
    binary = base64.b64decode(data['content'])
    path = os.path.join(UPLOAD_PDF, data['filename'])
    with open(path, 'wb') as f:
        f.write(binary)
    # extraer texto
    reader = PdfReader(io.BytesIO(binary))
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    dtm = re.search(r'(DTM[^\n]*)', text, re.I)
    desc = re.search(r'STATION NAME:[^\n]*\n([^\n]*)', text, re.I)
    # emitir datos al cliente
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
    # simplemente agregar
    maqs.append(data)
    with open(BASE_MAQ, 'w', encoding='utf-8') as f:
        json.dump(maqs, f, ensure_ascii=False, indent=4)
    emit('receive_maquinado', data, broadcast=True)
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email    = request.form['email'].strip().lower()
        pwd      = request.form['password']
        pwd2     = request.form['password2']

        if pwd != pwd2:
            flash("Las contraseñas no coinciden", "error")
            return redirect(url_for('register'))

        users = load_users()
        if any(u['email'] == email for u in users):
            flash("Ese correo ya está registrado", "error")
            return redirect(url_for('register'))

        next_id = max([u['id'] for u in users], default=0) + 1
        users.append({
            "id": next_id,
            "username": username,
            "email": email,
            "password": encrypt_pwd(pwd),
            "profile_pic": None
        })
        save_users(users)

        session['user_id'] = next_id
        return redirect(url_for('index'))

    return render_template('register.html')


# Login
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        pwd   = request.form['password']

        users = load_users()
        user = next((u for u in users if u['email']==email), None)
        if not user or decrypt_pwd(user['password']) != pwd:
            flash("Usuario o contraseña inválidos", "error")
            return redirect(url_for('login'))

        session['user_id'] = user['id']
        return redirect(url_for('index'))

    return render_template('login.html')


# Recuperar contraseña
@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    recovered = None
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        users = load_users()
        user = next((u for u in users if u['email']==email), None)
        if user:
            recovered = decrypt_pwd(user['password'])
        else:
            flash("Correo no registrado", "error")
    return render_template('forgot_password.html', recovered=recovered)


# Perfil (ver/editar datos + subir foto)
@app.route('/profile', methods=['GET','POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    users = load_users()
    user = next((u for u in users if u['id']==session['user_id']), None)
    if not user:
        session.pop('user_id')
        return redirect(url_for('login'))

    if request.method=='POST':
        # editar username/email
        user['username'] = request.form['username'].strip()
        user['email']    = request.form['email'].strip().lower()

        # si cambió password
        if request.form.get('password'):
            user['password'] = encrypt_pwd(request.form['password'])

        # subir foto
        pic = request.files.get('profile_pic')
        if pic and pic.filename:
            fn = f"user_{user['id']}_{uuid.uuid4().hex}{os.path.splitext(pic.filename)[1]}"
            path = os.path.join(USER_FILES_DIR, fn)
            pic.save(path)
            user['profile_pic'] = fn

        save_users(users)
        flash("Perfil actualizado", "success")
        return redirect(url_for('profile'))

    return render_template('profile.html', user=user)


# Logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))


# Servir fotos de perfil
@app.route('/archivos/<path:filename>')
def archivos(filename):
    return send_from_directory(USER_FILES_DIR, filename)
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
