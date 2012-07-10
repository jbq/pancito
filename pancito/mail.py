import Cheetah.Template
import email.header
import os.path
import pancito

def encodeHeader(v):
    return email.header.Header(v, 'utf-8').encode()

def writeMail(user, maildir, template):
    with open(os.path.join(maildir, "%02u" % user['rowid']), "w") as f:
        t = Cheetah.Template.Template(file=template)
        t.orderUrl = 'http://m.pancito.fr/order?userId=%s&t=%s' % (user['rowid'], pancito.genToken(user))
        t.unsubscribeUrl = 'http://m.pancito.fr/unsubscribe?userId=%s&t=%s' % (user['rowid'], pancito.genToken(user))
        t.email = user['email']
        t.encodeHeader = encodeHeader
        content = unicode(t)
        f.write(content.encode('utf-8'))

