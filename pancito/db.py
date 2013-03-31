import datetime
import sqlite3
import pytz
import pancito

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
        if adhesion is None:
            return None
        d = self.toDisplayCreationTime(adhesion)
        d['extraAmount'] = self.computeExtraAmount(adhesion)
        d['orderAmount'] = self.computeOrderAmount(adhesion)
        paidAmount = adhesion['amount'] + d['extraAmount']
        d['balance'] = paidAmount - d['orderAmount']
        d['debugBalance'] = "%s + %s - %s" % (adhesion['amount'], d['extraAmount'], d['orderAmount'])
        d['displayBalance'] = pancito.displayAmount(d['balance'])
        d['displayAmount'] = pancito.displayAmount(paidAmount)
        d['displayOrderAmount'] = pancito.displayAmount(d['orderAmount'])
        return d

    def computeExtraAmount(self, adhesion):
        c = self.conn.cursor()
        c.execute("SELECT coalesce(sum(amount), 0) FROM extra_payment WHERE contract_id = ? AND user_id = ?", (adhesion['contract_id'], adhesion['user_id']))
        return c.fetchone()[0]

    def computeOrderAmount(self, adhesion):
        c = self.conn.cursor()
        c.execute("SELECT sum(quantity) AS quantity, * FROM bakeorder INNER JOIN bake ON bake.rowid = bakeid INNER JOIN product ON product.id = productid WHERE contract_id = ? AND userid = ? GROUP BY productid", (adhesion['contract_id'], adhesion['user_id']))
        orders = c.fetchall()

        orderAmount = 0
        for order in orders:
            orderAmount += order['quantity'] * order['itemprice']
        return orderAmount

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

    def getBakeOrdersByUser(self, contractIds=None):
        c = self.conn.cursor()
        if contractIds is not None and len(contractIds) > 0:
            contractCondition  = "contract_id IN (%s)" % ', '.join(contractIds)
        else:
            contractCondition = "contract_id is not null"
        c.execute("SELECT bakeorder.rowid, bakeorder.*, itemprice from bakeorder inner join product ON product.id = productid WHERE bakeid IN (SELECT rowid FROM bake WHERE %s)" % contractCondition)
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
        d['place'] = self.getPlace(row['place_id'])
        return d

    def getContractsByPlace(self):
        contracts = {}
        c = self.conn.cursor()
        c.execute("SELECT rowid, * FROM contract order by startdate")
        for row in c.fetchall():
            # Overwrites contract with same place_id to keep the one with latest
            # startdate
            contracts[row['place_id']] = row

        return contracts

    def getPlace(self, placeId):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * FROM places WHERE id = ?", (placeId,))
        return c.fetchone()

    def toDisplayUser(self, row):
        if row is None:
            return None
        d = dict(row)
        d['currentAdhesion'] = self.getCurrentAdhesion(row['id'])
        d['adhesions'] = list(self.getUserAdhesionList(row['id']))
        d['extra_payments'] = list(self.getUserExtraPaymentList(row['id']))
        d['place'] = self.getPlace(row['place_id'])
        return d

    def toDisplayBake(self, row):
        if row is None:
            return None
        d = dict(row)
        d['bakedatetime'] = datetime.datetime.strptime(d['bakedate'], "%Y-%m-%d")
        d['bakedate'] = d['bakedatetime'].date()
        d['contract'] = self.getContract(d['contract_id'])
        return d

    def getFutureBakes(self, contractId=None, places=None):
        c = self.conn.cursor()
        conditions = ["bakedate >= CURRENT_DATE"]
        if contractId is not None:
            conditions.append("contract_id = %s" % contractId)
        if places is not None:
            conditions.append("contract_id IN (SELECT id FROM contract where place_id IN (%s))" % ", ".join(places))
        q = "SELECT rowid, * from bake WHERE %s" % " AND ".join(conditions)
        c.execute(q)
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

    def getContractsForIds(self, contractIds):
        c = self.conn.cursor()
        for contractId in contractIds:
            c.execute("SELECT rowid, * from contract WHERE id = ?", (contractId,))
            row = c.fetchone()
            if row is not None:
                yield self.toDisplayContract(row)

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

    def getUserByEmail(self, email):
        assert isinstance(email, basestring)
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE email = ?", (email,))
        return self.toDisplayUser(c.fetchone())

    def getUser(self, userId):
        assert isinstance(userId, int)
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE id = ?", (userId,))
        return self.toDisplayUser(c.fetchone())

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
        assert isinstance(user, dict), "Expecting %s for user param, got %s" % (dict, type(user))
        c = self.conn.cursor()
        c.execute("UPDATE user SET ismailing = ?, unsubscribe_time=datetime('now') WHERE id = ?", (mailing, user['id'],))
        self.conn.commit()

    def getUsers(self, ismailing=None, ismember=None, isorder=None, bakes=None):
        c = self.conn.cursor()
        params = []
        conditions = ["1"]
        if ismailing is not None:
            conditions.append("ismailing = ?")
            params.append(ismailing)
        if ismember is not None:
            conditions.append("ismember = ?")
            params.append(ismember)
        if isorder is not None:
            # Whether user has orders or not for the specified bakes
            if isorder is True:
                not_keyword = ''
            else:
                not_keyword = ' NOT'
            conditions.append("id%s IN (SELECT userid FROM bakeorder WHERE bakeid IN (%s))" % (not_keyword, ", ".join([str(x['rowid']) for x in bakes]),))
        q = "SELECT * from user WHERE %s" % " AND ".join(conditions)
        c.execute(q, params)
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
        c.execute("SELECT * FROM adhesion INNER JOIN contract ON contract.id = contract_id WHERE user_id = ? ORDER BY enddate DESC LIMIT 1", (userId,))

        if c.rowcount == 0:
            return None
        return self.toDisplayAdhesion(c.fetchone())

    def getAdhesion(self, userId, contractId):
        c = self.conn.cursor()
        c.execute("SELECT * FROM adhesion WHERE contract_id = ? AND user_id = ?", (contractId, userId))
        return self.toDisplayAdhesion(c.fetchone())
