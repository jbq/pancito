# coding=utf-8
import Cheetah.Template
import email.header
import os.path
import pancito
import sqlite3
import email.mime.multipart
import email.mime.text
import email.mime.application
import subprocess

_maildir = None
def maildir():
    if _maildir is not None:
        return _maildir

    globals()['_maildir'] = "tmp/mail"
    if not(os.path.exists(_maildir)):
        os.makedirs(_maildir)
    else:
        if len(os.listdir(_maildir)) > 0:
            raise Exception("tmp/mail is not empty, aborting to prevent side effects.")
    return _maildir

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

def writeMail(user, mailData):
    assert isinstance(user, sqlite3.Row), "Expecting %s for user param, got %s" % (sqlite3.Row, type(user))

    with open(os.path.join(maildir(), "%02u" % user['id']), "w") as f:
        f.write(mailData)

def mail_template_with_pdf_attachment(user, t, pdfData):
    msg = email.mime.multipart.MIMEMultipart()
    text = email.mime.text.MIMEText(mail_template(user, t), "plain", "utf-8")
    pdf = email.mime.application.MIMEApplication(pdfData, "pdf")
    msg.attach(text)
    msg.attach(pdf)
    msg['From'] = "Jean-Baptiste Quenot <jbq@pancito.fr>"
    msg['To'] = t.email
    msg['Subject'] = t.encodeHeader(t.subject)
    pdf.add_header('Content-Disposition', 'attachment', filename='Contrat Pancito.pdf')
    return msg.as_string()

def buildContractEmail(user, contract, pdfData):
    assert isinstance(user, sqlite3.Row), "Expecting %s for user param, got %s" % (sqlite3.Row, type(user))
    assert isinstance(contract, dict), "Expecting %s for contract param, got %s" % (dict, type(contract))

    template = os.path.join(pancito.datadir, "mail/contract.tmpl")
    t = Cheetah.Template.Template(file=template)
    t.subject = "Contrat pain"
    t.contract = contract
    t.adhesionUrl = "http://m.pancito.fr/adhesion?u=%s&c=%s&t=%s" % (user['id'], contract['id'], pancito.genToken(user, contract['id']))
    return pancito.mail.mail_template_with_pdf_attachment(user, t, pdfData)

def sendMail(mailData):
    p = subprocess.Popen(["sendmail", "-it"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.stdin.write(mailData)
    p.stdin.close()
    sc = p.wait()
    if sc != 0:
        raise Exception("Command returned status %s: %s.\nOutput:\n%s\nError:\n%s" % (sc, cmd, p.stdout.read(), p.stderr.read()))
