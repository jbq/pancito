import datetime
import sqlite3
import pytz

createTables = [
'''CREATE TABLE user (
    id integer primary key autoincrement not null,
    name text not null,
    email text unique not null,
    address text,
    postcode text,
    locality text,
    phone text,
    ismember boolean not null default 0,
    ismailing boolean not null default 1,
    creation_time datetime not null default current_timestamp,
    email_confirm_time datetime,
    unsubscribe_time datetime,
    balance int not null default 0
)''',

'''
CREATE TABLE contract (
    id integer primary key autoincrement not null,
    startdate date not null,
    enddate date not null,
    place text not null,
    timeslot text not null,
    creation_time datetime not null default current_timestamp
)''',

'''
CREATE TABLE adhesion (
    contract_id int not null,
    user_id int not null,
    creation_time datetime not null default current_timestamp,
    amount int not null,
    paperwork_verified datetime,
    unique(contract_id, user_id)
)''',

# contract_id initially empty
'''CREATE TABLE adhesionorder (
    contract_id int,
    user_id int not null,
    productid int not null,
    quantity int not null default 0,
    creation_time datetime not null default current_timestamp,
    unique(contract_id, user_id, productid)
)''',

'''CREATE TABLE bake (
    bakedate date not null,
    contract_id,
    creation_time datetime not null default current_timestamp
)''',

'''CREATE TABLE product (
    id integer primary key autoincrement not null,
    name text not null,
    itemprice int not null,
    creation_time datetime not null default current_timestamp
)''',

'''CREATE TABLE bakeorder (
    bakeid int not null,
    userid int not null,
    productid int not null,
    quantity int not null default 0,
    creation_time datetime not null default current_timestamp,
    unique(bakeid, userid, productid)
)''']

class ClientError(Exception):
    pass

class EmailAlreadyExists(ClientError):
    pass

class DBManager(object):
    def __init__(self, conn):
        self.conn = conn

    def getBakeOrdersByUserId(self, bakeId):
        return self.getBakeOrdersByField(bakeId, "userid", "productid")

    def toDisplayAdhesion(self, adhesion):
        return self.toDisplayCreationTime(adhesion)

    def toDisplayOrder(self, order):
        return self.toDisplayCreationTime(order)

    def toDisplayOrderWithAmount(self, order):
        if order is None:
            return None
        o = dict(order)
        o['amount'] = o['quantity'] * o['itemprice']
        return o

    def toDisplayCreationTime(self, order):
        if order is None:
            return None
        order = dict(order)
        ct = datetime.datetime.strptime(order['creation_time'], "%Y-%m-%d %H:%M:%S")
        ct = ct.replace(tzinfo=pytz.timezone('UTC'))
        order['creation_time'] = ct.astimezone(pytz.timezone('Europe/Paris'))
        return order

    def getBakeOrdersByUser(self):
        c = self.conn.cursor()
        c.execute("SELECT bakeorder.rowid, bakeorder.*, itemprice from bakeorder inner join product ON product.id = productid WHERE bakeid IN (SELECT rowid FROM bake WHERE contract_id IS NOT NULL)")
        orders = {}
        for order in c.fetchall():
            userId = order['userId']

            try:
                orders[userId].append(self.toDisplayOrderWithAmount(order))
            except KeyError:
                orders[userId] = [self.toDisplayOrderWithAmount(order)]

        return orders

    def getBakeOrders(self, bakeId, userId):
        assert isinstance(bakeId, (int, long)), "Expecting %s for bakeId, got %s" % (int, type(bakeId))
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bakeorder WHERE bakeid = ? AND userid = ?", (bakeId, userId))
        return c.fetchall()

    def getBakeOrdersByField(self, bakeId, field, subfield):
        assert isinstance(bakeId, (int, long)), "Expecting %s for bakeId, got %s" % (int, type(bakeId))
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bakeorder WHERE bakeid = ?", (bakeId,))
        ordersByField = {}
        for order in c.fetchall():
            try:
                ordersByField[order[field]][order[subfield]] = self.toDisplayOrder(order)
            except KeyError:
                ordersByField[order[field]] = {order[subfield]: self.toDisplayOrder(order)}
        return ordersByField

    def _mergeOrders(self, orders1, orders2):
        d = {}

        for dd in (orders1, orders2):
            for k, qty in dd.items():
                try:
                    d[k] += qty
                except KeyError:
                    d[k] = qty
        return d

    def extractQuantity(self, order):
        assert isinstance(order, dict), "Expecting dict, got %s: %s" % (type(order), repr(order))

        d = {}
        for k, v in order.items():
            d[k] = v['quantity']
        return d

    def mergeOrders(self, ordersByUserList):
        d = {}
        for ordersByUser in ordersByUserList:
            for userId, orders in ordersByUser.items():
                try:
                    d[userId] = self._mergeOrders(self.extractQuantity(orders), d[userId])
                except KeyError:
                    d[userId] = self._mergeOrders(self.extractQuantity(orders), {})
        return d

    def bakeOrdersByDate(self, bakes):
        """
        For admin, build an overview of all bake orders for the specified bakes.
        Bakes with same bake date are grouped in the same entry.  Return value is
        a dict of the form {bakedate: [bakes]}
        """
        bakesByDate = {}
        for bake in bakes:
            ordersByUser = self.getBakeOrdersByUserId(bake['rowid'])
            try:
                bakesByDate[bake['bakedate']].append(ordersByUser)
            except KeyError:
                bakesByDate[bake['bakedate']] = [ordersByUser]

        for bakeDate, ordersByUserList in bakesByDate.items():
            bakesByDate[bakeDate] = self.mergeOrders(ordersByUserList)

        for bakeDate in sorted(bakesByDate.keys()):
            yield (bakeDate, bakesByDate[bakeDate])

    def buildBakesWithOrders(self, bakes, userId):
        for bake in bakes:
            bake["orders"] = self.getBakeOrders(bake['rowid'], userId)
            yield bake

    def buildBakesWithOrdersByUser(self, bakes):
        for bake in bakes:
            bake["orders"] = self.getBakeOrdersByUserId(bake['rowid'])
            yield bake

    def toDisplayContract(self, row):
        d = dict(row)
        for field in ('startdate', 'enddate'):
            d['%stime'%field] = datetime.datetime.strptime(d[field], "%Y-%m-%d")
            d[field] = d['%stime'%field].date()
        return d

    def toDisplayUser(self, row):
        d = dict(row)
        d['currentAdhesion'] = self.getCurrentAdhesion(row['id'])
        d['adhesions'] = list(self.getUserAdhesionList(row['id']))
        d['extra_payments'] = list(self.getUserExtraPaymentList(row['id']))
        return d

    def toDisplayBake(self, row):
        d = dict(row)
        d['bakedatetime'] = datetime.datetime.strptime(d['bakedate'], "%Y-%m-%d")
        d['bakedate'] = d['bakedatetime'].date()
        return d

    def getFutureBakes(self, contractId=None):
        c = self.conn.cursor()
        conditions = ["bakedate >= CURRENT_DATE"]
        if contractId is not None:
            conditions.append("contract_id = %s" % contractId)
        c.execute("SELECT rowid, * from bake WHERE %s" % " AND ".join(conditions))
        for row in c.fetchall():
            yield self.toDisplayBake(row)

    def getBakes(self, contractId=None):
        if contractId is not None:
            assert isinstance(contractId, (int, long)), "Expecting %s for contractId, got %s" % (int, type(contractId))
        c = self.conn.cursor()
        statements = ["SELECT rowid, * from bake"]
        args = []
        if contractId is not None:
            statements.append("WHERE contract_id = ?")
            args.append(contractId)
        statements.append("ORDER BY bakedate")
        c.execute(" ".join(statements), args)
        for row in c.fetchall():
            yield self.toDisplayBake(row)

    def getBakesForIds(self, bakeIds):
        c = self.conn.cursor()
        for bakeId in bakeIds:
            c.execute("SELECT rowid, * from bake WHERE rowid = ?", (bakeId,))
            row = c.fetchone()
            if row is not None:
                yield self.toDisplayBake(row)

    def getProducts(self):
        c = self.conn.cursor()
        c.execute("SELECT * from product")
        return c.fetchall()

    def getBake(self, bakeId):
        assert isinstance(bakeId, int)
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bake WHERE rowid = ?", (bakeId,))
        return self.toDisplayBake(c.fetchone())

    def getContract(self, contractId):
        assert isinstance(contractId, int)
        c = self.conn.cursor()
        c.execute("SELECT * from contract WHERE id = ?", (contractId,))
        return self.toDisplayContract(c.fetchone())

    def getUser(self, userId):
        assert isinstance(userId, int)
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE id = ?", (userId,))
        return c.fetchone()

    def register(self, fields, d):
        assert isinstance(fields, (list, tuple))
        assert isinstance(d, dict)
        c = self.conn.cursor()
        query = "INSERT INTO user (%s) VALUES (%s)" % (", ".join(fields), ", ".join(['?' for k in fields]))
        params = [d[k] for k in fields]
        try:
            c.execute(query, params)
        except sqlite3.IntegrityError:
            raise EmailAlreadyExists(fields)
        return c.lastrowid

    def updateRegistration(self, userId, fields, d):
        assert isinstance(userId, int)
        assert isinstance(fields, (list, tuple))
        assert isinstance(d, dict)
        c = self.conn.cursor()
        pairs = ["%s = %s" % (k, '?') for k in fields]
        query = "UPDATE user SET %s WHERE id = ?" % ", ".join(pairs)
        params = [d[k] for k in fields]
        params.append(userId)
        try:
            c.execute(query, params)
        except sqlite3.IntegrityError:
            raise EmailAlreadyExists(fields)

    def setUserMailing(self, user, mailing):
        assert isinstance(mailing, bool), "Expecting %s for mailing param, got %s" % (bool, type(mailing))
        assert isinstance(user, sqlite3.Row), "Expecting %s for user param, got %s" % (sqlite3.Row, type(user))
        c = self.conn.cursor()
        c.execute("UPDATE user SET ismailing = ?, unsubscribe_time=datetime('now') WHERE id = ?", (mailing, user['id'],))
        self.conn.commit()

    def getUsers(self, ismailing=False):
        c = self.conn.cursor()
        params = []
        clauses = ["SELECT * from user"]
        if ismailing:
            clauses.append("WHERE ismailing = ?")
            params.append(ismailing)
        c.execute(" ".join(clauses), params)
        for row in c.fetchall():
            yield self.toDisplayUser(row)

    def getUsersWithOrder(self, bakes):
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE id IN (SELECT userid FROM bakeorder WHERE bakeid IN (%s))" % (", ".join([str(x['rowid']) for x in bakes]),))
        for row in c.fetchall():
            yield self.toDisplayUser(row)

    def deleteBakeOrders(self, user_id, bake_id):
        assert isinstance(user_id, int)
        assert isinstance(bake_id, int)
        c = self.conn.cursor()
        c.execute("DELETE FROM bakeorder WHERE userid = ? AND bakeid = ?", (user_id, bake_id))

    def deleteAdhesionOrders(self, user_id, contractId=None):
        assert isinstance(user_id, int)
        c = self.conn.cursor()
        if contractId is None:
            c.execute("DELETE FROM adhesionorder WHERE user_id = ? AND contract_id is null", (user_id,))
        else:
            c.execute("DELETE FROM adhesionorder WHERE user_id = ? AND contract_id = ?", (user_id, contractId))

    def addAdhesionOrder(self, user_id, product_id, qty, contractId=None):
        assert isinstance(user_id, int)
        assert isinstance(product_id, int)
        assert isinstance(qty, int)
        c = self.conn.cursor()
        fields = ['user_id', 'productid', 'quantity']
        values = [user_id, product_id, qty]
        if contractId is not None:
            fields.append("contract_id")
            values.append(contractId)
        placeholders = ['?'] * len(fields)
        c.execute("INSERT INTO adhesionorder (%s) VALUES (%s)" % (", ".join(fields), ", ".join(placeholders)), values)

    def createAdhesion(self, user_id, contractId, amount):
        assert isinstance(user_id, int)
        assert isinstance(contractId, int)
        c = self.conn.cursor()
        fields = ['user_id', 'contract_id', 'amount']
        values = [user_id, contractId, amount]
        placeholders = ['?'] * len(fields)
        c.execute("INSERT INTO adhesion (%s) VALUES (%s)" % (", ".join(fields), ", ".join(placeholders)), values)

    def addBakeOrder(self, user_id, bake_id, product_id, qty):
        assert isinstance(user_id, int)
        assert isinstance(bake_id, int)
        assert isinstance(product_id, int)
        assert isinstance(qty, int)
        c = self.conn.cursor()
        c.execute("INSERT INTO bakeorder (userid, bakeid, productid, quantity) VALUES (?, ?, ?, ?)", (user_id, bake_id, product_id, qty))

    def resetEmail(self, user_id):
        assert isinstance(user_id, int)
        c = self.conn.cursor()
        c.execute("UPDATE user SET email_confirm_time = NULL WHERE id = ?", (user_id,))
        self.conn.commit()

    def confirmEmail(self, user_id):
        assert isinstance(user_id, int)
        c = self.conn.cursor()
        c.execute("UPDATE user SET email_confirm_time = datetime('now') WHERE id = ?", (user_id,))
        self.conn.commit()

    def getAdhesionOrders(self, userId, contractId=None):
        c = self.conn.cursor()
        if contractId is not None:
            c.execute("SELECT * FROM adhesionorder WHERE contract_id = ? AND user_id = ?", (contractId, userId))
        else:
            c.execute("SELECT * FROM adhesionorder WHERE user_id = ?", (userId,))
        return c.fetchall()

    def getUserExtraPaymentList(self, userId):
        c = self.conn.cursor()
        c.execute("SELECT * FROM extra_payment WHERE user_id = ?", (userId,))
        for row in c.fetchall():
            yield self.toDisplayAdhesion(row)

    def getUserAdhesionList(self, userId):
        c = self.conn.cursor()
        c.execute("SELECT * FROM adhesion WHERE user_id = ? AND paperwork_verified is not null", (userId,))
        for row in c.fetchall():
            yield self.toDisplayAdhesion(row)

    def getCurrentAdhesion(self, userId):
        c = self.conn.cursor()
        c.execute("SELECT * FROM adhesion WHERE user_id = ? AND contract_id IN (SELECT id FROM contract WHERE enddate >= current_date)", (userId,))
        if c.rowcount == 0:
            return None
        return self.toDisplayAdhesion(c.fetchone())

    def getAdhesion(self, userId, contractId):
        c = self.conn.cursor()
        c.execute("SELECT * FROM adhesion WHERE contract_id = ? AND user_id = ?", (contractId, userId))
        return self.toDisplayAdhesion(c.fetchone())
