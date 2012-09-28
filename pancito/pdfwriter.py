import tempfile
from datetime import date
from itools.fs import lfs
from itools.handlers import RWDatabase
from itools.odf.odf import stl_to_odt, ODTFile
import pancito
import os.path
import subprocess

class Struct:
    def __init__(self, **entries):
        self.__dict__.update(entries)
    def update(self, **entries):
        self.__dict__.update(entries)

class ContractGenerator:
    def gencontract(self, user, contract):
        c = self.conn.cursor()
        for field in ('startdate', 'enddate'):
            contract[field] = contract[field].strftime("%d %B %Y")
        c.execute("SELECT sum(quantity) AS quantity, * FROM bakeorder INNER JOIN bake ON bake.rowid = bakeid INNER JOIN product ON product.id = productid WHERE contract_id = ? AND userid = ? GROUP BY productid", (contract['id'], user['id']))
        orders = c.fetchall()
        if len(orders) == 0:
            raise Exception("No order for %s, skipping" % user['name'])
        info = Struct(**user)
        info.update(**contract)
        info.date = date.today().strftime("%d %B %Y")
        c.execute("SELECT count(*) FROM bake WHERE contract_id = ?", (contract['id'],))
        info.bakeCount = c.fetchone()[0]

        # FIXME
        orderdisplays = []
        orderAmount = 0
        for order in orders:
            orderdisplays.append("%s %s" % (order['quantity'], order['name']))
            orderAmount += order['quantity'] * order['itemprice']
        info.order = " et ".join(orderdisplays)
        info.balance = pancito.displayAmount(orderAmount - user['balance'])

        print "Writing contract for", user['name']
        rw_database = RWDatabase(fs=lfs)
        handler = rw_database.get_handler(os.path.join(pancito.datadir, 'model.odt'))
        document = stl_to_odt(handler, info)
        handler = ODTFile(string=document)
        tmpfile = tempfile.mktemp(".odt")
        tmpdir = tempfile.mkdtemp("", "pdfwriter")
        rw_database.set_handler(tmpfile, handler)
        rw_database.save_changes()

        if not os.path.exists("/usr/bin/libreoffice"):
            raise Exception("Cannot find libreoffice")

        cmd = ["libreoffice", "--headless", "--invisible", "--convert-to", "pdf", "--outdir", tmpdir, tmpfile]
        p = subprocess.Popen(cmd)
        sc = p.wait()
        if sc != 0:
            raise Exception("Command returned status %s: %s" % (sc, cmd))

        return os.path.join(tmpdir, os.path.basename(tmpfile).replace('.odt', '.pdf'))
