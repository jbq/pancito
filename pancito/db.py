import datetime
import sqlite3

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
    unsubscribe_time datetime
)''',

'''
CREATE TABLE contract (
    startdate date unique not null,
    enddate date unique not null,
    creation_time datetime not null default current_timestamp,
    unique(startdate, enddate)
)''',

'''
CREATE TABLE adhesion (
    contract_id int not null,
    user_id int not null,
    creation_time datetime not null default current_timestamp,
    unique(contract_id, user_id)
)''',

'''CREATE TABLE bake (
    bakedate date unique not null,
    contract_id,
    creation_time datetime not null default current_timestamp
)''',

'''CREATE TABLE product (
    name text,
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

class DBManager(object):
    def getBakeOrdersByUserId(self, bakeId):
        return self.getBakeOrdersByField(bakeId, "userid", "productid")

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

    def buildSpecifiedBakesWithOrdersByUser(self, bakes):
        for bake in bakes:
            bake["orders"] = self.getBakeOrdersByUserId(bake['rowid'])
            yield bake

    def buildBakesWithOrdersByUser(self, bakes):
        for bake in bakes:
            bake["orders"] = self.getBakeOrdersByUserId(bake['rowid'])
            yield bake

    def buildBakesWithOrdersByProduct(self):
        for bake in self.getBakes():
            bake["orders"] = self.getBakeOrdersByProductId(bake['rowid'])
            yield bake

    def toDisplayBake(self, row):
        d = dict(row)
        d['bakedatetime'] = datetime.datetime.strptime(d['bakedate'], "%Y-%m-%d")
        d['bakedate'] = d['bakedatetime'].date()
        return d

    def getFutureBakes(self):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bake WHERE bakedate >= CURRENT_DATE")
        for row in c.fetchall():
            yield self.toDisplayBake(row)

    def getBakes(self):
        c = self.conn.cursor()
        c.execute("SELECT rowid, * from bake")
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
        c.execute("SELECT rowid, * from product")
        return c.fetchall()

    def getUser(self, userId):
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE id = ?", (userId,))
        return c.fetchone()

    def register(self, fields, d):
        c = self.conn.cursor()
        query = "INSERT INTO user (%s) VALUES (%s)" % (", ".join(fields), ", ".join(['?' for k in fields]))
        params = [d[k] for k in fields]
        c.execute(query, params)
        self.conn.commit()
        return c.lastrowid

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
        return c.fetchall()

    def getUsersWithOrder(self, bakeIds):
        c = self.conn.cursor()
        c.execute("SELECT * from user WHERE id IN (SELECT userid FROM bakeorder WHERE bakeid IN (?))", (", ".join(bakeIds),))
        return c.fetchall()

    def deleteBakeOrders(self, user_id, bake_id):
        assert isinstance(user_id, int)
        assert isinstance(bake_id, int)
        c = self.conn.cursor()
        c.execute("DELETE FROM bakeorder WHERE userid = ? AND bakeid = ?", (user_id, bake_id))

    def addBakeOrder(self, user_id, bake_id, product_id, qty):
        assert isinstance(user_id, int)
        assert isinstance(bake_id, int)
        assert isinstance(product_id, int)
        assert isinstance(qty, int)
        c = self.conn.cursor()
        c.execute("INSERT INTO bakeorder (userid, bakeid, productid, quantity) VALUES (?, ?, ?, ?)", (user_id, bake_id, product_id, qty))

    def confirmEmail(self, user_id):
        assert isinstance(user_id, int)
        c = self.conn.cursor()
        c.execute("UPDATE user SET email_confirm_time = datetime('now') WHERE id = ?", (user_id,))
        self.conn.commit()
