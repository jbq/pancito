# coding=utf-8
import os.path, StringIO, sys, operator, datetime, cgi, shutil
import Cheetah.Template
import sqlite3, hashlib
import db, mail, pdfwriter
import traceback, subprocess
import log
import locale
import syslog
locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
syslog.openlog("pancito", syslog.LOG_PID)
root = os.path.dirname(os.path.dirname(__file__))
datadir = os.path.join(root, 'data')
with open(os.path.join(root, "secret")) as f:
    secretKey = f.read().rstrip()

def opendb():
    dbpath = os.path.join(datadir, 'db/pancito.db')

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

def genToken(user, extraArgs=None):
    s = hashlib.sha1()
    s.update(str(user['id']))
    s.update(user['email'])
    s.update(secretKey)
    if extraArgs is not None:
        s.update(str(extraArgs))

    return s.hexdigest()[:7]

def verifyToken(user, token, extraArgs=None):
    if token is None:
        raise BadRequest("Missing token")

    if token != genToken(user, extraArgs):
        raise BadRequest("Token mismatch for user %s" % user['id'])

def displayAmount(v):
    assert isinstance(v, int)
    vv = str(v).ljust(3, "0")
    return "%s,%s" % (vv[:-2], vv[-2:])

class BadRequest(Exception):
    pass

class App(db.DBManager, pdfwriter.ContractGenerator):
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
            log.log_exc()
            log.notice("Environ: %s" % repr(self.environ))
            self._startResponse("400 Bad Request", [('Content-Type', 'text/html; charset=utf-8')])
            return "<h1>Requête incorrecte</h1><p>L'équipe technique a été informée du problème, veuillez renouveler l'opération dans quelques minutes.</p>"
        except:
            log.log_exc()
            log.notice("Environ: %s" % repr(self.environ))
            self._startResponse("500 Internal Server Error", [('Content-Type', 'text/html; charset=utf-8')])
            return "<h1>Erreur du serveur</h1><p>L'équipe technique a été informée du problème, veuillez renouveler l'opération dans quelques minutes.</p>"

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
        template.environ = self.environ
        template.query = self.environ['QUERY_STRING']
        return template

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
            displayedContractIds = params.getlist('dc')
            template.allOrdersByUser = self.getBakeOrdersByUser(displayedContractIds)
            displayedBakeIds = params.getlist('b')
            displayedPlaces = params.getlist('p')
            if len(displayedPlaces) == 0:
                displayedPlaces = None
            userCriteria = {}
            for option in params.getlist("du"):
                for criterium in ('mailing', 'member', 'order'):
                    if option == criterium:
                        userCriteria["is%s"%criterium] = True
                    elif option == "no%s" % criterium:
                        userCriteria["is%s"%criterium] = False

            displayedBakes = list(self.getBakesForIds(displayedBakeIds))

            if len(displayedBakes) == 0:
                displayedContracts = list(self.getContractsForIds(displayedContractIds))
                if len(displayedContracts) > 0:
                    displayedBakes = []
                    for x in displayedContracts:
                        displayedBakes += list(self.getBakes(x['id']))
                else:
                    displayedBakes = list(self.getFutureBakes(places=displayedPlaces))

            userCriteria['bakes'] = displayedBakes
            template.users = self.getUsers(**userCriteria)

            template.bakeOrdersByDate = list(self.bakeOrdersByDate(displayedBakes))
            template.bakes = displayedBakes
            template.contractsByPlace = self.getContractsByPlace()
            self.addHeader("Content-Type", "text/html; charset=utf-8")
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

            self.addHeader("Content-Type", "text/html; charset=utf-8")
            return unicode(template).encode('utf-8')

        if uri == "/register" :
            userId = None
            contractId = None

            try:
                userId = int(params.getfirst('u'))
            except :
                pass

            try:
                contractId = int(params.getfirst('c'))
            except :
                pass

            template = self.getTemplate("register")
            template.orders = {}
            self.conn = opendb()

            if userId is not None:
                template.user = self.getUser(userId)
                # contract id is included in token
                verifyToken(template.user, params.getfirst('t'), params.getfirst('c'))
                if contractId is not None:
                    template.orders = self.getAdhesionOrders(userId, contractId)
                if len(template.orders) == 0:
                    template.orders = self.getAdhesionOrders(userId)
            else:
                template.user = None

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
                    p = params.getfirst(f)
                    if p is None:
                        return None
                    v = p.strip().decode('utf8')
                    if v is None:
                        return None
                    d[f] = v
                return d

            if method == "POST":
                fields = ('name', 'email', 'address', 'postcode', 'locality', 'phone', 'comment')
                d = getRegistration(fields)

                if d is None:
                    template.error = "Veuillez vérifier que tous les champs sont bien renseignés!"
                elif '@' not in d['email']:
                    template.error = "Veuillez saisir une adresse email valide"
                elif not checkProducts():
                    template.error = "Veuillez préciser votre commande hebdomadaire avec au moins un produit!"

                if template.error is None:
                    try:
                        if userId is None:
                            email = True
                            rowid = self.register(fields, d)
                            user = self.getUser(rowid)
                        else:
                            if template.user['email'] != d['email']:
                                email = True
                                self.resetEmail(userId)
                            else:
                                email = False

                            self.updateRegistration(userId, fields, d)
                            # Fetch user again from db to have updated fields
                            # and compute proper token
                            user = self.getUser(userId)

                        self.deleteAdhesionOrders(user['id'], contractId)
                        for product in template.products:
                            try:
                                qty = int(params.getfirst("product.%s" % product['id']))
                            except:
                                qty = 0
                            self.addAdhesionOrder(user['id'], product['id'], qty, contractId)

                        if userId is not None and contractId is not None:
                            adhesionUri = '/adhesion?u=%s&c=%s&t=%s' % (userId, contractId, genToken(user, contractId))

                        if email:
                            t = Cheetah.Template.Template(file="%s/mail/registrationEmail.tmpl" % datadir)
                            if userId is not None and contractId is not None:
                                t.emailConfirmationUrl = 'http://m.pancito.fr%s&emailConfirmed=1' % adhesionUri
                            else:
                                t.emailConfirmationUrl = 'http://m.pancito.fr/emailConfirmation?userId=%s&t=%s' % (user['id'], genToken(user))
                            mail.sendMail(mail.mail_template(user, t))

                        self.conn.commit()
                        template.emailSent = email
                        template.success = True

                        if email is False and userId is not None and contractId is not None:
                            # No need to confirm email, go to adhesion form directly
                            self.status = "302 Moved Temporarily"
                            self.addHeader("Location", adhesionUri)
                            return

                    except db.EmailAlreadyExists:
                        template.error = "L'adresse email que vous avez renseigné existe déjà.  L'inscription a déjà été effectuée."

            self.addHeader("Content-Type", "text/html; charset=utf-8")
            return unicode(template).encode('utf-8')

        if uri == "/emailConfirmation":
            template = self.getUserTemplate("emailConfirmation")
            # FIXME choose contract with newadhesion = True
            openContract = 3
            template.contract = self.getContract(openContract)
            self.confirmEmail(template.user['id'])
            template.futureBakes = list(self.getFutureBakes(openContract))
            self.addHeader("Content-Type", "text/html; charset=utf-8")
            return unicode(template).encode('utf-8')

        if uri == "/contract":
            userId = None
            contractId = None

            try:
                userId = int(params.getfirst('u'))
            except :
                pass

            try:
                contractId = int(params.getfirst('c'))
            except :
                pass

            # contract id is included in token
            self.conn = opendb()
            user = self.getUser(userId)
            contract = self.getContract(contractId)
            verifyToken(user, params.getfirst('t'), params.getfirst('c'))

            self.addHeader("Content-Type", "application/pdf")
            self.addHeader("Content-Disposition", "attachment; filename=Contrat Pancito.pdf")
            contractFile = self.gencontract(user, contract)

            with open(contractFile) as f:
                contractData = f.read()

            contractDir = os.path.join(datadir, "Contrats", str(contract['id']))
            if not os.path.exists(contractDir):
                os.makedirs(contractDir)
            shutil.move(contractFile, os.path.join(contractDir, "%s Contrat %s.pdf" % (datetime.date.today().strftime("%Y-%m-%d"), user['name'].encode('utf-8'))))
            mail.sendMail(mail.buildContractEmail(user, contract, contractData))
            self.conn.commit()
            return contractData

        if uri == "/adhesion":
            try:
                userId = int(params.getfirst('u'))
            except Exception, e:
                raise BadRequest(repr(e))

            try:
                contractId = int(params.getfirst('c'))
            except Exception, e:
                raise BadRequest(repr(e))

            template = self.getTemplate("adhesion")
            self.conn = opendb()
            if params.getfirst("emailConfirmed") is not None:
                self.confirmEmail(userId)

            template.user = self.getUser(userId)
            template.contract = self.getContract(contractId)
            # contract id is included in token
            verifyToken(template.user, params.getfirst('t'), params.getfirst('c'))
            template.products = self.getProducts()
            template.adhesionOrders = self.getAdhesionOrders(userId, contractId)
            if len(template.adhesionOrders) == 0:
                template.adhesionOrders = self.getAdhesionOrders(userId)
                if len(template.adhesionOrders) == 0:
                    raise Exception("No orders for contract %s and user %s" % (contractId, userId))
            template.adhesion = self.getAdhesion(userId, contractId)

            if method == "POST":
                editedBakes = self.getEditedBakes()
                self.processBakeOrders(editedBakes, userId)
                self.conn.commit()
                template.success = True

            displayedBakes = list(self.getBakes(contractId))
            template.bakes = list(self.buildBakesWithOrders(displayedBakes, userId))
            for i, bake in enumerate(template.bakes):
                bake['initialOrders'] = {}

            self.addHeader("Content-Type", "text/html; charset=utf-8")
            return unicode(template).encode('utf-8')

        if uri == "/order":
            template = self.getUserTemplate("order")
            template.products = self.getProducts()
            template.adhesionOrders = None
            try:
                contractId = int(params.getfirst('c'))
            except:
                contractId = None

            initialBakes = None
            if method == "GET":
                editedBakes = list(self.getBakesForIds(params.getlist('b')))
                if len(editedBakes) == 0:
                    editedBakes = list(self.getFutureBakes(contractId))
                initialBakes = list(self.buildBakesWithOrdersByUser(editedBakes))
            elif method == "POST":
                editedBakes = self.getEditedBakes()
                # Don't display existing order warning when we do a POST
                initialBakes = None
                self.processBakeOrders(editedBakes, template.user['id'])
                self.conn.commit()
                template.success = u"Votre commande a bien été prise en compte, merci!"

            template.bakes = list(self.buildBakesWithOrdersByUser(editedBakes))
            for i, bake in enumerate(template.bakes):
                if initialBakes is not None:
                    bake['initialOrders'] = initialBakes[i]['orders']
                else:
                    bake['initialOrders'] = {}

            self.addHeader("Content-Type", "text/html; charset=utf-8")
            return unicode(template).encode('utf-8')

        if uri.startswith("/knobs/"):
            knobsDir = os.path.join(root, "knobs")
            with open(os.path.join(knobsDir, os.path.basename(uri))) as f:
                self.addHeader("Content-Type", "image/png")
                return f.read()

        #raise Exception("No controller for %s.  Environ: %s" % (uri, repr(self.environ)))
        self.status = "404 Not Found"
        return ""

    def getEditedBakes(self):
        params = self.getQueryParameters()
        # 'b' param may not be specified in URL so another 'sb' for
        # hidden bake id in form
        return list(self.getBakesForIds(params.getlist('sb')))

    def processBakeOrders(self, editedBakes, userId):
        params = self.getQueryParameters()

        for bake in editedBakes:
            self.deleteBakeOrders(userId, bake['rowid'])
            for product in self.getProducts():
                try:
                    qty = int(params.getfirst("bake.%s.%s" % (bake['rowid'], product['id'])))
                except:
                    qty = 0
                self.addBakeOrder(userId, bake['rowid'], product['id'], qty)

def application(environ, start_response):
    app = App(environ, start_response)
    return app.handleRequest()
