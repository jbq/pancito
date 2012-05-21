# coding=utf-8
import os.path, StringIO, sys, operator, datetime, cgi
import Cheetah.Template
import sqlite3, hashlib
import pytz

createTableUser = '''
CREATE TABLE user (
    name text unique not null,
    email text unique not null,
    creation_time datetime not null default current_timestamp
)'''

createTableBake = '''CREATE TABLE bake (
    bakedate date unique not null,
    creation_time datetime not null default current_timestamp
)'''

createTableProduct = '''CREATE TABLE product (
    name text,
    creation_time datetime not null default current_timestamp
)'''

createTableOrder = '''CREATE TABLE bakeorder (
    bakeid int not null,
    userid int not null,
    productid int not null,
    quantity int not null default 0,
    creation_time datetime not null default current_timestamp,
    unique(bakeid, userid, productid)
)'''

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
        c.execute(createTableUser)
        c.execute(createTableBake)
        c.execute(createTableProduct)
        c.execute(createTableOrder)

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

class App:
    def __init__(self, environ, start_response):
        self.environ = environ
        self._startResponse = start_response
        self.status = "200 OK"
        self.headers = []
        self.__params = None

    def addHeader(self, name, value):
        self.headers.append((name, value))

    def handleRequest(self):
        value = self.processRequest()
        self._startResponse(self.status, self.headers)
        return value
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
        template.genToken = genToken
        params = self.getQueryParameters()
        template.params = params
        return template

    def getBakeOrdersByUserId(self, bakeId):
        return self.getBakeOrdersByField(bakeId, "userid", "productid")

    def displayOrder(self, order):
        order = dict(order)
        ct = datetime.datetime.strptime(order['creation_time'], "%Y-%m-%d %H:%M:%S")
        ct = ct.replace(tzinfo=pytz.timezone('UTC'))
        order['creation_time'] = ct.astimezone(pytz.timezone('Europe/Paris'))
        return order

    def getBakeOrdersByField(self, bakeId, field, subfield):
        assert isinstance(bakeId, (int, long)), "Expecting %s for bakeId, got %s" % (int, type(bakeId))
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bakeorder WHERE bakeid = ?", (bakeId,))
        ordersByField = {}
        for order in c.fetchall():
            try:
                ordersByField[order[field]][order[subfield]] = self.displayOrder(order)
            except KeyError:
                ordersByField[order[field]] = {order[subfield]: self.displayOrder(order)}
        return ordersByField

    def buildBakesWithOrdersByUser(self, bakes):
        for bake in bakes:
            b = dict(bake)
            b["orders"] = self.getBakeOrdersByUserId(bake['rowid'])
            yield b

    def buildBakesWithOrdersByProduct(self, bakes):
        for bake in bakes:
            b = dict(bake)
            b["orders"] = self.getBakeOrdersByProductId(bake['rowid'])
            yield b

    def getBakes(self):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bake")
        for row in c.fetchall():
            d = dict(row)
            d['bakedate'] = datetime.datetime.strptime(d['bakedate'], "%Y-%m-%d")
            yield d

    def getBakesForIds(self, bakeIds):
        c = self.conn.cursor()
        for bakeId in bakeIds:
            c.execute("SELECT rowid, * from bake WHERE rowid = ?", (bakeId,))
            row = c.fetchone()
            if row is not None:
                yield row

    def getProducts(self):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from product")
        return c.fetchall()

    def getUser(self, userId):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from user WHERE rowid = ?", (userId,))
        return c.fetchone()

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
                    c.execute("INSERT INTO user (name, email) VALUES (?, ?)", (name, email))
                    userid = c.lastrowid
                    conn.commit()
                except sqlite3.IntegrityError:
                    template.error = u"Cet utilisateur est déjà enregistré"
            return unicode(template).encode('utf-8')

        if uri == "/admin/%s" % secretKey:
            self.conn = opendb()
            template=self.getTemplate("admin")
            template.bakes = list(self.buildBakesWithOrdersByUser(list(self.getBakes())))

            c = self.conn.cursor()
            c.execute("SELECT rowid, * from user")
            template.users = c.fetchall()
            self.addHeader("Content-Type", "text/html")
            return unicode(template).encode('utf-8')

        if uri == "/order":
            template=self.getTemplate("order")

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
            bakes = list(self.getBakesForIds(params.getlist('b')))
            if len(bakes) == 0:
                # admin displays all dates
                bakes = list(self.getBakes())

            initialBakes = None
            if method == "GET":
                initialBakes = list(self.buildBakesWithOrdersByUser(bakes))
            elif method == "POST":
                # Don't display existing order warning when we do a POST
                initialBakes = None
                c = self.conn.cursor()

                for bake in bakes:
                    c.execute("DELETE FROM bakeorder WHERE userid = ? AND bakeid = ?", (userId, bake['rowid']))
                    for product in template.products:
                        try:
                            qty = int(params.getfirst("bake.%s.%s" % (bake['rowid'], product['rowid'])))
                        except:
                            qty = 0
                        c.execute("INSERT INTO bakeorder (userid, bakeid, productid, quantity) VALUES (?, ?, ?, ?)", (userId, bake['rowid'], product['rowid'], qty))

                self.conn.commit()
                template.success = u"Votre commande a bien été prise en compte, merci!"

            template.bakes = list(self.buildBakesWithOrdersByUser(bakes))
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
