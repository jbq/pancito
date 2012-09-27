# coding=utf-8
import os.path, StringIO, sys, operator, datetime, cgi
import Cheetah.Template
import sqlite3, hashlib
import pytz
import db, mail
import traceback, subprocess

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
    s.update(str(user['id']))
    s.update(user['email'])
    s.update(secretKey)

    return s.hexdigest()[:7]

def verifyToken(user, token):
    if token is None:
        raise BadRequest("Missing token")

    if token != genToken(user):
        raise BadRequest("Token mismatch")

def displayAmount(v):
    assert isinstance(v, int)
    vv = str(v)
    return "%s,%s" % (vv[:-2], vv[-2:])

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
            traceback.print_exc()
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
        template.displayAmount = displayAmount
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

        if uri == "/register" :
            template = self.getTemplate("register")
            self.conn = opendb()
            template.products = self.getProducts()

            def checkProducts():
                for product in self.getProducts():
                    v = params.getfirst("product.%s" % product['id'])
                    if v is not None:
                        try:
                            if int(v) > 0:
                                return True
                        except:
                            return False
                return False

            def getRegistration(fields):
                d = {}
                for f in fields:
                    v = params.getfirst(f).decode('utf8')
                    if v is None:
                        return None
                    d[f] = v
                return d

            if method == "POST":
                fields = ('name', 'email', 'address', 'postcode', 'locality', 'phone')
                d = getRegistration(fields)

                if d is None:
                    template.error = "Veuillez vérifier que tous les champs sont bien renseignés!"
                if not checkProducts():
                    template.error = "Veuillez préciser votre commande hebdomadaire avec au moins un produit!"

                if template.error is None:
                    try:
                        rowid = self.register(fields, d)
                        user = self.getUser(rowid)
                        self.deleteAdhesionOrders(user['id'])
                        for product in template.products:
                            try:
                                qty = int(params.getfirst("product.%s" % product['id']))
                            except:
                                qty = 0
                            self.addAdhesionOrder(user['id'], product['id'], qty)
                        cmd = ["sendmail", "-it"]
                        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                        p.stdin.write(mail.mail_template(user, "%s/mail/registrationEmail.tmpl" % datadir))
                        p.stdin.close()
                        sc = p.wait()
                        if sc != 0:
                            raise Exception("Command returned status code %s: %s" % (sc, cmd))
                        self.conn.commit()
                        template.success = True
                    except db.EmailAlreadyExists:
                        template.error = "L'adresse email que vous avez renseigné existe déjà.  L'inscription a déjà été effectuée."

            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri == "/emailConfirmation":
            template = self.getUserTemplate("emailConfirmation")
            self.confirmEmail(template.user['id'])
            template.futureBakes = list(self.getFutureBakes())
            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri == "/order":
            template = self.getUserTemplate("order")
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
                    self.deleteBakeOrders(template.user['id'], bake['rowid'])
                    for product in template.products:
                        try:
                            qty = int(params.getfirst("bake.%s.%s" % (bake['rowid'], product['id'])))
                        except:
                            qty = 0
                        self.addBakeOrder(template.user['id'], bake['rowid'], product['id'], qty)

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
