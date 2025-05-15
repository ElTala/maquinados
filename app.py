from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import base64, io, re, json
from PyPDF2 import PdfReader
import re
import os
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)
UPLOAD_PDF  = os.path.join('static', 'uploads', 'pdf')
UPLOAD_STEP = os.path.join('static', 'uploads', 'step')
os.makedirs(UPLOAD_PDF,  exist_ok=True)
os.makedirs(UPLOAD_STEP, exist_ok=True)
@app.route('/')
def index():
    with open('bases/proyectos.json', encoding='utf-8') as f:
        proyectos = json.load(f)
    return render_template('index.html',proyectos=proyectos)

@app.route('/pedidos')
def dashboard():
    with open('bases/proyectos.json', encoding='utf-8') as f:
        proyectos = json.load(f)
    try:
        with open('bases/maquinados.json', encoding='utf-8') as f:
            maquinados = json.load(f)
    except:
        maquinados = []
    grouped = {}
    for m in maquinados:
        grouped.setdefault(m['proyecto'], []).append(m)
    return render_template('pedidos.html',
                           proyectos=proyectos,
                           grouped_maquinados=grouped)

@socketio.on('new_maquinado')
def handle_new_maquinado(data):
    path = 'bases/maquinados.json'
    try:
        with open(path, encoding='utf-8') as f:
            maqs = json.load(f)
    except:
        maqs = []
    updated = False
    for m in maqs:
        if m['proyecto'] == data['proyecto'] and m['partnumber'] == data['partnumber']:
            m['cantidad'] = str(int(m['cantidad']) + int(data['cantidad']))
            m['pdf']  = data.get('pdf') or ""
            m['step'] = data.get('step') or ""
            data = m
            updated = True
            break
    if not updated:
        maqs.append(data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(maqs, f, ensure_ascii=False, indent=4)
    emit('receive_maquinado', data, broadcast=True)
    emit('play_sound', broadcast=True)


@socketio.on('send_form_data')
def handle_send_form_data(data):
    path = 'bases/proyectos.json'
    try:
        with open(path, encoding='utf-8') as f:
            proyectos = json.load(f)
    except FileNotFoundError:
        proyectos = []
    proyectos.append(data)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(proyectos, f, ensure_ascii=False, indent=4)
    emit('receive_form_data', data, broadcast=True)
    emit('play_sound', broadcast=True)

@socketio.on('upload_step')
def handle_step(data):
    binary = base64.b64decode(data['content'])
    path   = os.path.join(UPLOAD_STEP, data['filename'])
    with open(path, 'wb') as f:
        f.write(binary)
    emit('step_received', {'filename': data['filename']}, room=request.sid)
      
@socketio.on('upload_pdf')
def handle_pdf(data):
    binary = base64.b64decode(data['content'])
    path   = os.path.join(UPLOAD_PDF, data['filename'])
    with open(path, 'wb') as f:
        f.write(binary)
    reader = PdfReader(io.BytesIO(binary))
    text   = '\n'.join(page.extract_text() or '' for page in reader.pages)
    dtm    = re.search(r'(DTM[^\n]*)', text, re.I)
    desc   = re.search(r'STATION NAME:[^\n]*\n([^\n]*)', text, re.I)
    emit('pdf_received', {'filename': data['filename']}, room=request.sid)
    emit('pdf_data', {'dtm': dtm.group(1).strip() if dtm else None,
                      'descripcion': desc.group(1).strip() if desc else None},
         room=request.sid)
    
@app.route('/visualizador')
def viewer():
    file_url = request.args.get('file')
    return render_template('visualizador.html', file_url=file_url)

@app.route('/nuevoProyecto')
def nuevoproyecto():
    file_url = request.args.get('file')
    return render_template('nuevoProyecto.html', file_url=file_url)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
