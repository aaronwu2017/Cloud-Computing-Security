import time, bcrypt, os, uuid
from datetime import datetime, timedelta, timezone
from google.cloud import datastore
from flask import Flask, render_template, jsonify, request, redirect, send_from_directory, url_for, flash
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, EqualTo
from flask_wtf import FlaskForm
# check cookie in the browse console:   javascript: alert(document.cookie)

app = Flask(__name__)
# generate a 24 bits random key as a form exchange secret key, preventing CSRF attack. 
# also for flask flash function
app.secret_key = os.urandom(24) 
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(seconds = 1)

DS = datastore.Client()
EVENT = 'event' # Name of the event table.
ROOT = DS.key('Entities', 'root') # Name of root key, can be anything.
USER = 'user' # 'event' # Name of the event table.
SESSION = 'session' # 'event' # Name of the event table.

# generate old events for migration testing
# entity = datastore.Entity(key = DS.key(EVENT, parent=ROOT))
# entity.update( {'name': 'old_event', 'date': '2050-01-01'})
# DS.put(entity)


''' 
***************************  Below is the events management section  ****************************************
''' 

# get function, get all the existing events from google cloud datastore
@app.route('/events',methods = ["GET"])
def getEvents():
    token = request.cookies.get('user_cookie')
    
    if not check_session(token):
        return login()
    
    user_key = get_user_key(token)
    # events = DS.query(kind=EVENT, ancestor=ROOT).fetch()
    query = DS.query(kind=EVENT, ancestor=ROOT)
    # only get events belonging to the current user based on the user_key
    query.add_filter('user_key', '=', user_key)
    events = query.fetch()
    #TODO: calculate the remaining time on the server side, and return the sorted data based on the remaining time to the browser, so that we could sort events correctly and display them. The browser will also calculate the remaining time every second 
    return jsonify({
        'events':sorted([{'name': event['name'], 'date': event['date'], 'id': event.id} for event in events], key=lambda element:(element['date'])), 
        'error': None
    })
    
# post function, variables: {name} {date}, add new event to google cloud datastore 
@app.route('/event', methods=['POST'])
def addEvents():
    token = request.cookies.get('user_cookie')
    
    if not check_session(token):
        return login()
    # adds events to the current user_key
    user_key = get_user_key(token)
    event = request.json
    entity = datastore.Entity(key=DS.key(EVENT, parent=ROOT))
    entity.update({
        'name': event['name'],
        'date': event['date'],
        'user_key': user_key
    })
    DS.put(entity)
    
    return getEvents()

# delete events based on the id of the event in the datastore
@app.route('/delete/<int:event_id>', methods=['DELETE'])
def delEvent(event_id):
    token = request.cookies.get('user_cookie')
    
    if not check_session(token):
        return login()
    
    DS.delete(DS.key(EVENT, event_id, parent=ROOT))
    
    return getEvents()


''' 
*******************************  Below is the user authentication section  ***********************************
'''     
    
# the class for user login  
class LoginForm(FlaskForm):
    
    username = StringField('username', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])

# the class for user registration
class RegisterForm(FlaskForm):
    
    username = StringField('username', validators=[DataRequired()])
    password = PasswordField('password', validators=[DataRequired()])
    
# main page
@app.route('/')
def index():
    token = request.cookies.get('user_cookie')
    
    if not check_session(token): 
        return redirect(url_for("login"))
    else:
        return send_from_directory("static", "index.html")
    

@app.route('/register', methods=['GET', 'POST']) 
def register():
    
    if request.method == 'GET':
        return send_from_directory('static', 'register.html')
    
    # when the request method is post, the user wants to create an account
    form = RegisterForm()
    username = form.username.data.strip()
    password = form.password.data.strip()
    # username = request.form.get('username').strip()
    # password = request.form.get('password').strip()
    # TODO: input password twice

    accounts = check_user(username)
    
    if len(accounts) >= 1: 
        # when this user already exists
        return redirect(url_for("register"))
        #return used_username()
    
    # if the username from the form is valid
    user_key = create_user(username, password)
    token = set_session(user_key)
    
    # for the first user, migrate old events to him
    query = DS.query(kind = USER)
    users = list(query.fetch())
    if len(users) == 1:
        migrate(username)
        
    resp = redirect(url_for("index"))
    resp.set_cookie('user_cookie', token)

    return resp


def used_username():
    return send_from_directory('static', 'register_Uusername.html')


@app.route('/login', methods=['GET', 'POST'])  
def login():
    
    if request.method == 'GET':
        return send_from_directory('static', 'login.html')
    
    # when the request method is post, the user has inputted the username and the password
    form = LoginForm()
    username = form.username.data.strip()
    password = form.password.data.strip()
    # username = request.form.get('username').strip()
    # password = request.form.get('password').strip()
    
    accounts = check_user(username)

    if len(accounts) == 0:
        # When the username doesn't exist
        #return redirect(url_for("login"))
        return wrong_username()
    
    right_password = accounts[0]["password"]
    user_key = accounts[0].id         # uses the id of every user generated by the datastore as a unique user_key
    # compare the inputted password and the password in the datastore
    if bcrypt.hashpw(password.encode(), right_password) == right_password:
        token = set_session(user_key)
        
        resp = redirect(url_for("index"))
        resp.set_cookie('user_cookie', token)

        return resp
    else:
        # When the password is wrong
        # return redirect(url_for("login"))
        return wrong_password()
    

def wrong_username():
    return send_from_directory('static', 'login_Wusername.html')

def wrong_password():
    return send_from_directory('static', 'login_Wpassword.html')
    

@app.route('/logout')
def logout():
    # get the token from the cookie, then uses token to query the user_key in the SESSION entity in the datastore
    token = request.cookies.get('user_cookie')
    user_key = get_user_key(token)
    
    #if a user login for many times and doesn't logout, he can have many valid sessions with the same user_key.
    query = DS.query(kind = SESSION)
    query.add_filter('user_key', '=', user_key)
    sessions = list(query.fetch())
    
    for session in sessions:
        DS.delete(session.key)
    
    # delete the cookie and return to the login page
    resp = redirect(url_for("login"))
    resp.delete_cookie('user_cookie')
    
    return resp
    
# get all the users whose username is the same as the given username
def check_user(username):
    query = DS.query(kind = USER)
    query.add_filter('username', '=', username)
    
    return list(query.fetch())


def create_user(username, password):
    if not username:
        return
    
    user = datastore.Entity(key = DS.key(USER))
    user.update({
        'username': username,
        # hashes the password by bcrypt then stores in the datastore
        'password': bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)),
        # 'id': uuid.uuid4()  # use uuid to generate a unique id as Primary key
    })
    DS.put(user)
    
    return user.id
    
# when login or register, set a new session of 1 hour for a user
def set_session(user_key):
    
    token = str(uuid.uuid4())     # a unique session ID, will be stored in the cookie and the SESSION entity in the datastore
    expire = datetime.now(timezone.utc) + timedelta(hours = 1)   # calculate the expiration time based on UTC timezone

    session = datastore.Entity(key=DS.key(SESSION))
    session.update({
        "token": token,
        'user_key': user_key,
        'expire': expire
    })
    DS.put(session)

    return token

# get the user_key from the SESSION entity in the datastore based on the token
def get_user_key(token):
    query = DS.query(kind = SESSION)
    query.add_filter('token', '=', token)
    
    return list(query.fetch())[0]['user_key']

# get the token from the cookie, then check if the session is valid
def check_session(token):
    
    if not token:
        return False
    
    query = DS.query(kind = SESSION)
    query.add_filter('token', '=', token)
    session = list(query.fetch())
    
    # if no session for this token
    if not session: 
        return False
    
    # if the session doesn't have user_key
    user_key = session[0]['user_key']
    if not user_key:
        return None
    
    # if the session will never expire
    if not session[0]['expire']:
        return False
    
    # if the session expires, deletes all the expired session for this user
    if session[0]['expire'] <= datetime.now(timezone.utc): 
        query = DS.query(kind = SESSION)
        query.add_filter('user_key', '=', user_key)
        results = list(query.fetch())
        for result in results:
            DS.delete(result.key)
            
        return False

    return True

# migrates the old events over to the first user
# there is old events 
def migrate(username):
    query = DS.query(kind = EVENT, ancestor=ROOT)
    old_events = query.fetch()
    # get the user id as user_key
    query = DS.query(kind = USER)
    query.add_filter('username', '=', username)
    user_key = list(query.fetch())[0].id
    
    # updates all the old events with the first user's user_key and deletes original old events
    for old_event in list(old_events):
        entity = datastore.Entity(key = DS.key(EVENT, parent=ROOT))
        entity.update({'name': old_event['name'], 'date': old_event['date'], 'user_key': user_key})
        DS.put(entity)
        
        DS.delete(old_event.key)


if __name__ == '__main__':
    # For local testing
    app.run(host='127.0.0.1', port=7070, debug=True)