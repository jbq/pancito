import Cheetah.Template
import email.header
import os.path
import pancito
import sqlite3

def encodeHeader(v):
    return email.header.Header(v, 'utf-8').encode()

def mail_template(user, t):
    assert isinstance(t, Cheetah.Template.Template)
    assert isinstance(user, sqlite3.Row), "Expecting %s for user param, got %s" % (sqlite3.Row, type(user))
    t.orderUrl = 'http://m.pancito.fr/order?userId=%s&t=%s' % (user['id'], pancito.genToken(user))
    t.emailConfirmationUrl = 'http://m.pancito.fr/emailConfirmation?userId=%s&t=%s' % (user['id'], pancito.genToken(user))
    t.unsubscribeUrl = 'http://m.pancito.fr/unsubscribe?userId=%s&t=%s' % (user['id'], pancito.genToken(user))
    t.email = user['email']
    t.encodeHeader = encodeHeader
    content = unicode(t)
    return content.encode('utf-8')

def writeMail(user, maildir, template):
    assert isinstance(template, Cheetah.Template.Template)
    assert isinstance(user, sqlite3.Row), "Expecting %s for user param, got %s" % (sqlite3.Row, type(user))
    with open(os.path.join(maildir, "%02u" % user['id']), "w") as f:
        f.write(mail_template(user, template))

