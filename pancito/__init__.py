# coding=utf-8
import os.path, StringIO, sys, operator, datetime, cgi
import Cheetah.Template
import sqlite3, hashlib
import pytz
import db

import locale
locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')

root = os.path.dirname(os.path.dirname(__file__))
datadir = os.path.join(root, 'data')
with open(os.path.join(root, "secret")) as f:
    secretKey = f.read().rstrip()

def opendb():
    dbpath = os.path.join(datadir, 'pancito.db')

    if not(os.path.exists(dbpath)):
        newDB = True
    else:
        newDB = False

    conn = sqlite3.connect(dbpath)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if newDB:
        for createTable in db.createTables:
            c.execute(createTable)

    return conn

def genToken(user):
    s = hashlib.sha1()
    s.update(str(user['rowid']))
    s.update(user['email'])
    s.update(secretKey)

    return s.hexdigest()[:7]

def verifyToken(user, token):
    if token is None:
        raise BadRequest("Missing token")

    if token != genToken(user):
        raise BadRequest("Token mismatch")

class BadRequest(Exception):
    pass

class App(db.DBManager):
    def __init__(self, environ, start_response):
        self.environ = environ
        self._startResponse = start_response
        self.status = "200 OK"
        self.headers = []
        self.__params = None

    def addHeader(self, name, value):
        self.headers.append((name, value))

    def handleRequest(self):
        try:
            value = self.processRequest()
            self._startResponse(self.status, self.headers)
            return value
        except BadRequest:
            self._startResponse("400 Bad Request", [('Content-Type', 'text/html')])
            return "<h1>Requête incorrecte</h1>"
        #try:
        #except:
        #    import cgitb
        #    traceback.print_tb()
        #    self._startResponse("500 Internal Server Error", [('Content-Type', 'text/html')])
        #    return ""
        #    return cgitb.html(sys.exc_info())

    def getQueryParameters(self):
        if self.__params is None:
            fp = None
            if self.environ.has_key('wsgi.input'):
                fp = self.environ['wsgi.input']

            self.__params = cgi.FieldStorage(fp, environ=self.environ)

        return self.__params

    def getTemplate(self, t):
        template = Cheetah.Template.Template(file=os.path.join(root, "templates/%s.tmpl" % t))
        template.error = None
        template.success = None
        template.warning = None
        template.genToken = genToken
        template.now = datetime.datetime.now()
        params = self.getQueryParameters()
        template.params = params
        return template

    def displayOrder(self, order):
        order = dict(order)
        ct = datetime.datetime.strptime(order['creation_time'], "%Y-%m-%d %H:%M:%S")
        ct = ct.replace(tzinfo=pytz.timezone('UTC'))
        order['creation_time'] = ct.astimezone(pytz.timezone('Europe/Paris'))
        return order

    def getUserTemplate(self, templateName):
        template=self.getTemplate(templateName)
        params = self.getQueryParameters()

        try:
            userId = int(params.getfirst("userId"))
        except:
            raise BadRequest("No user id specified")

        self.conn = opendb()
        template.user = self.getUser(userId)
        if template.user is None:
            raise BadRequest("No such user")

        verifyToken(template.user, params.getfirst('t'))
        return template

    def processRequest(self):
        uri = self.environ['PATH_INFO']
        method = self.environ['REQUEST_METHOD']
        params = self.getQueryParameters()

        if uri == "/addFriend" and method == "POST":
            template=self.getTemplate("addFriend")

            name = params.getfirst('name')
            email = params.getfirst('email')

            if name is None:
                template.error = "Veuillez entrer le nom"
            if email is None:
                template.error = "Veuillez entrer l'adresse email"

            if template.error is None:
                try:
                    self.addUser(name, email)
                except sqlite3.IntegrityError:
                    template.error = u"Cet utilisateur est déjà enregistré"
            return unicode(template).encode('utf-8')

        if uri == "/admin/%s" % secretKey:
            self.conn = opendb()
            template=self.getTemplate("admin")
            displayedBakeIds = params.getlist('b')
            displayMailedUsers = (params.getfirst('du') == "mailed")
            displayAllUsers = (params.getfirst('du') == "all")
            displayedBakes = list(self.getBakesForIds(displayedBakeIds))

            if len(displayedBakes) == 0:
                displayedBakes = self.getBakes()
                template.users = self.getUsers(ismailing=displayMailedUsers)
            else:
                if displayAllUsers or displayMailedUsers:
                    template.users = self.getUsers(ismailing=displayMailedUsers)
                else:
                    template.users = self.getUsersWithOrder(displayedBakeIds)

            template.bakes = list(self.buildSpecifiedBakesWithOrdersByUser(displayedBakes))
            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri == "/unsubscribe":
            template = self.getUserTemplate("unsubscribe")

            if bool(template.user['ismember']) is True:
                template.error = "En tant qu'adhérent vous ne pouvez pas vous désinscrire de la liste Pancito"
            elif bool(template.user['ismailing']) is False:
                template.warning = "Vous êtes déjà désinscrit de la liste Pancito"
            else:
                self.setUserMailing(template.user, False)
                template.success = "Vous avez été désinscrit de la liste Pancito"

            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri == "/order":
            template = self.getUserTemplate("order")

            try:
                userId = int(params.getfirst("userId"))
            except:
                raise BadRequest("No user id specified")

            self.conn = opendb()
            template.user = self.getUser(userId)
            if template.user is None:
                raise BadRequest("No such user")

            verifyToken(template.user, params.getfirst('t'))

            template.products = self.getProducts()

            initialBakes = None
            if method == "GET":
                editedBakes = list(self.getBakesForIds(params.getlist('b')))
                if len(editedBakes) == 0:
                    editedBakes = list(self.getFutureBakes())
                initialBakes = list(self.buildBakesWithOrdersByUser(editedBakes))
            elif method == "POST":
                # Don't display existing order warning when we do a POST
                initialBakes = None

                # 'b' param may not be specified in URL so another 'sb' for
                # hidden bake id in form
                editedBakes = list(self.getBakesForIds(params.getlist('sb')))
                for bake in editedBakes:
                    self.deleteBakeOrders(userId, bake['rowid'])
                    for product in template.products:
                        try:
                            qty = int(params.getfirst("bake.%s.%s" % (bake['rowid'], product['rowid'])))
                        except:
                            qty = 0
                        self.addBakeOrder(userId, bake['rowid'], product['rowid'], qty)

                self.conn.commit()
                template.success = u"Votre commande a bien été prise en compte, merci!"

            template.bakes = list(self.buildBakesWithOrdersByUser(editedBakes))
            for i, bake in enumerate(template.bakes):
                if initialBakes is not None:
                    bake['initialOrders'] = initialBakes[i]['orders']
                else:
                    bake['initialOrders'] = {}

            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri.startswith("/knobs/"):
            knobsDir = os.path.join(root, "knobs")
            with open(os.path.join(knobsDir, os.path.basename(uri))) as f:
                self.addHeader("Content-Type", "image/png")
                return f.read()

        #raise Exception("No controller for %s.  Environ: %s" % (uri, repr(self.environ)))
        self.status = "404 Not Found"
        return ""

def application(environ, start_response):
    app = App(environ, start_response)
    return app.handleRequest()
