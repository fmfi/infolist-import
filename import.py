#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Importne data z AIS exportu v XML formate do Posgre databazy.
"""

from __future__ import print_function

from xml.dom import minidom
try:
  from lxml import etree as ET
except ImportError:
  import xml.etree.ElementTree as ET
import re
import sys
import glob
import os
import os.path
import psycopg2
from contextlib import closing
import datetime
from contextlib import contextmanager

_context = []

def fmtcontext(d):
  return u' '.join(u'{}={}'.format(k, d[k]) for k in d)

@contextmanager
def context(**kwargs):
  _context.append(kwargs.copy())
  try:
    yield
  except:
    sys.stderr.write(fmtcontext(_context[-1]))
    sys.stderr.write('\n')
    raise
  finally:
    _context.pop()

def warn(text):
  sys.stderr.write(u' '.join(fmtcontext(x) for x in _context).encode('UTF-8'))
  sys.stderr.write(': ')
  sys.stderr.write(text.encode('UTF-8'))
  sys.stderr.write('\n')

def kod2skratka(kod):
  print(kod)
  skratka = re.match(r'^[^/]+/([^/]+)/', kod).group(1)
  print(kod,'=>',skratka)
  return skratka
  #return re.match(r'^[^/]+/(.+)/[^/]+$', kod).group(1)

def parse_formula(s):
  tokens = []
  separators = '() ,'
  newtoken = True
  for c in s:
    if c in separators:
      newtoken = True
      if c != ' ':
        tokens.append(c)
    else:
      if newtoken:
        tokens.append(c)
      else:
        tokens[-1] += c
      newtoken = False
  tokens2 = []
  for token in tokens:
    if token == ',':
      tokens2.append('AND')
    elif token == 'alebo':
      tokens2.append('OR')
    else:
      tokens2.append(token)
  num = 0
  for token in tokens2:
    if token == '(':
      num += 1
    elif token == ')':
      num -= 1
      if num < 0:
        raise ValueError('Zle uzatvorkovany vyraz')
  if num != 0:
    raise ValueError('Zle uzatvorkovany vyraz')
  return tokens2

def html_to_text(e):
  def flatten_inline(e):
    x = u''
    if e.text:
      x += e.text
    for child in e:
      x += flatten(child)
    if e.tail:
      x += e.tail
    return x.strip()
  
  ret = u''
  lastmode = None
  for child in e:
    if child.tag == 'p':
      inline = flatten_inline(child)
      if inline.startswith('-'):
        mode = 'ul'
      elif re.match(r'^\d+\.', inline):
        mode = 'ol'
      else:
        mode = 'p'
      if mode == 'ul' and lastmode == 'ul':
        ret += u'\n'
      elif mode == 'ol' and lastmode == 'ol':
        ret += u'\n'
      else:
        ret += u'\n\n'
      ret += inline
      lastmode = mode
    else:
      raise ValueError('Unsupported tag')
  return ret.strip()

def process_file(filename, lang='sk'):
    xmldoc = ET.parse(filename)
    root = xmldoc.getroot()
    organizacnaJednotka = root.find('organizacnaJednotka').text
    ilisty = root.find('informacneListy')
    
    # elementy, ktore sa budu parsovat z XML-ka
    elements = ('kod', 'skratka', 'nazov', 'kredit', 'sposobUkoncenia', 'sposobVyucby',
                'rozsahTyzdenny', 'rozsahSemestranly', 'obdobie', 'rokRocnikStudPlan',
                'kodSemesterStudPlan', 'jazyk', 'podmienujucePredmety', 'metodyStudia',
                'vyucujuciAll', 'zabezpecuju', 'datumSchvalenia', '_VH_', '_SO_', '_VV_',
                '_Z_', '_P_', '_O_', '_S_', 'vylucujucePredmety',
                'hodnoteniaPredmetu')

    map_metodyStudia = {u'prezenčná': 'P', u'dištančná': 'D', u'kombinovaná': 'K'}
    # vid ciselnik druh_cinnosti
    map_sposobVyucby = {u'Prednáška': 'P', u'Cvičenie': 'C', u'Samostatná práca': 'D',
      u'Kurz': 'K', u'Iná': 'I', u'Práce v teréne': 'T', u'Seminár': 'S',
      u'Laboratórne cvičenie': 'L', u'Prax': 'X', u'sústredenie': 'U',
      u'Exkurzia': 'E', u'Prednáška+Seminár': 'R',
      u'prednáška': 'P', u'cvičenie': 'C', u'samostatná práca': 'D',
      u'kurz': 'K', u'iná': 'I', u'práce v teréne': 'T', u'seminár': 'S',
      u'laboratórne cvičenie': 'L', u'prax': 'X', 
      u'exkurzia': 'E', u'prednáška+seminár': 'R'}

    data = []

    # spracovanie informacnych listov jednotlivych predmetov
    for il in ilisty.findall('informacnyList'):
      with context(line=getattr(il, 'sourceline', None)):
        d = {'lang' : lang, 'organizacnaJednotka': organizacnaJednotka}
        for e in elements:
            if il.find(e) is not None:
                if e.startswith('_'):
                    if e == '_VH_':
                        d[e] = il.find(e).findtext('texty/p')
                    else:
                        d[e] = html_to_text(il.find(e).find('texty'))
                elif e == 'vyucujuciAll':
                    d[e] = []
                    for vyucujuci in il.find(e).findall('vyucujuci'):
                        d[e].append({
                            #id = vyucujuci.find('id').text
                            'typ': vyucujuci.find('typ').text,
                            'plneMeno': vyucujuci.find('plneMeno').text
                        })
                elif e == 'hodnoteniaPredmetu':
                    d['celkovyPocetHodnotenychStudentov'] = il.find(e).find('celkovyPocetHodnotenychStudentov').text
                    celk = il.find(e).find('celkovyPocetVsetkychHodnoteni')
                    if celk is not None:
                      d['celkovyPocetVsetkychHodnoteni'] = celk.text
                    else:
                      d['celkovyPocetVsetkychHodnoteni'] = d['celkovyPocetHodnotenychStudentov']
                    d['hodnoteniaPredmetu'] = {}
                    s = 0
                    for hodnotenie in il.find(e).findall('hodnoteniePredmetu'):
                        d['hodnoteniaPredmetu'][hodnotenie.find('kod').text] =\
                        {
                            'pocetHodnoteni': hodnotenie.find('pocetHodnoteni').text,
                            'percentualneVyjadrenieZCelkPoctuHodnoteni': hodnotenie.find('percentualneVyjadrenieZCelkPoctuHodnoteni').text
                        }
                        s += int(hodnotenie.find('pocetHodnoteni').text)
                    assert(s == int(d['celkovyPocetVsetkychHodnoteni']))
                elif e == 'metodyStudia':
                    metodyStudia = il.find(e).findall('metodaStudia')
                    assert len(metodyStudia) > 0
                    if len(metodyStudia) != 1:
                        warn(u'Predmet %s ma viac metod studia, importujem iba prvu' % d['kod'])
                    d['metodaStudia'] = map_metodyStudia[metodyStudia[0].text]
                else:
                    d[e] = il.find(e).text
            else:
                d[e] = None
        
        with context(predmet=d['kod']):
            # vaha hodnotenia
            if not d['_VH_']:
                d['vahaSkusky'] = None
            elif not re.match('^\s*\d+\s*/\s*\d+\s*$', d['_VH_']):
                d['vahaSkusky'] = None
                warn(u'Nepodarilo sa sparsovat vahu skusky %s pre predmet %s' % (d['_VH_'], d['kod']))
            else:
                vahy = d['_VH_'].split('/')
                if len(vahy) != 2:
                  raise AssertionError(u'{} {}'.format(d['kod'], vahy))
                d['vahaSkusky'] = vahy[1]

            # parsovanie sposobu vyucby
            d['sposoby'] = []
            if not d['sposobVyucby']:
                warn(u'Nenasiel som sposob vyucby pre predmet %s.' % d['kod'])
            else:
                sposobVyucby = d['sposobVyucby'].split(' / ')
                if not d['rozsahTyzdenny']:
                  rozsahTyzdenny = None
                else:
                  rozsahTyzdenny = d['rozsahTyzdenny'].split(' / ')
                if not d['rozsahSemestranly']:
                  rozsahSemestranly = None
                else:
                  rozsahSemestranly = d['rozsahSemestranly'].split(' / ')
                if rozsahTyzdenny == None and rozsahSemestranly == None:
                  warn(u'Nenasiel som rozsah pre predmet %s' % d['kod'])
                else:
                  if rozsahTyzdenny == None:
                    rozsahTyzdenny = [None] * len(sposobVyucby)
                  if rozsahSemestranly == None:
                    rozsahSemestranly = [None] * len(sposobVyucby)
                  for i in range(len(sposobVyucby)):
                      if (i < len(rozsahTyzdenny)) and (rozsahTyzdenny[i] != None):
                        hodin = rozsahTyzdenny[i]
                        za_obdobie = 'T'
                      elif (i < len(rozsahSemestranly)):
                        hodin = rozsahSemestranly[i]
                        za_obdobie = 'S'
                      else:
                        hodin = 0
                        za_obdobie = 'T'
                      if re.match('^\d+[st]$', hodin):
                        warn(u'Pocet hodin %s je so suffixom, konvertujem' % hodin)
                        za_obdobie = hodin[-1].upper()
                        hodin = int(hodin[:-1])
                      elif not re.match('^\d+$', hodin):
                        warn(u'Pocet hodin "%s" nie je cislo, nahradzujem nulou' % hodin)
                        hodin = 0
                      else:
                        hodin = int(hodin)
                      x = {
                              'sposobVyucby': map_sposobVyucby[sposobVyucby[i]],
                              'rozsahHodin': hodin,
                              'rozsahZaObdobie': za_obdobie
                          }
                      d['sposoby'].append(x)
            
            if d['podmienujucePredmety']:
              d['podmienujucePredmety'] = parse_formula(d['podmienujucePredmety'])
            else:
              d['podmienujucePredmety'] = []
            
            if d['vylucujucePredmety']:
              d['vylucujucePredmety'] = parse_formula(d['vylucujucePredmety'])
            else:
              d['vylucujucePredmety'] = []

        data.append(d)

    return data

def import2db(con, data, user, iba_kody=None, dry_run=False):
    """ import do cistej db"""
    def vytvor_alebo_najdi_predmet(kod_predmetu, skratka=None):
      with closing(con.cursor()) as cur:
        if skratka == None:
          skratka = kod2skratka(kod_predmetu)
        cur.execute('''SELECT id FROM predmet WHERE kod_predmetu = %s''', (kod_predmetu,))
        row = cur.fetchone()
        if row:
          return row[0]
        else:
          cur.execute('''INSERT INTO predmet (kod_predmetu, skratka,
                        povodny_kod, povodna_skratka)
                      VALUES (%s, %s, %s, %s)
                      RETURNING id''',
                      (kod_predmetu, skratka, kod_predmetu, skratka))
          return cur.fetchone()[0]
    with closing(con.cursor()) as cur:
        for d in data:
            if iba_kody != None:
              if not iba_kody.match(d['kod']):
                warn(u'Preskakujem import infolistu pre predmet {}, lebo nematchuje regex'.format(d['kod']))
                continue
            # checkni duplikaty
            cur.execute('''
              SELECT 1
              FROM predmet p
              WHERE kod_predmetu=%s
              AND EXISTS (
                SELECT infolist
                FROM predmet_infolist pi
                WHERE pi.predmet = p.id
              )
              ''',
              (d['kod'],))
            is_duplicate = cur.fetchone() != None
            if is_duplicate:
                warn(u"Infolist pre predmet %s uz existuje" % d['kod'])
                continue
            warn('Vytvaram infolist pre predmet %s' % d['kod'])

            hodnotenia = {}
            for hodn in ['A', 'B', 'C', 'D', 'E', 'FX']:
              if 'hodnoteniaPredmetu' in d and hodn in d['hodnoteniaPredmetu']:
                hodnotenia[hodn] = d['hodnoteniaPredmetu'][hodn]['pocetHodnoteni']
              else:
                hodnotenia[hodn] = None
            
            def prepare_formula(tokens):
              idform = []
              referenced = set()
              for token in tokens:
                if token in ('(', ')', 'AND', 'OR', 'a', 'alebo'):
                  idform.append(token)
                else:
                  token_id = vytvor_alebo_najdi_predmet(token)
                  referenced.add(token_id)
                  idform.append(str(token_id))
              return idform, referenced
            
            podm_s_idckami, podm_predmety = prepare_formula(d['podmienujucePredmety'])
            vyluc_s_idckami, vyluc_predmety = prepare_formula(d['vylucujucePredmety'])
            
            cur.execute('''INSERT INTO infolist_verzia (
                podm_absol_percenta_skuska, hodnotenia_a_pocet,
                hodnotenia_b_pocet, hodnotenia_c_pocet, hodnotenia_d_pocet,
                hodnotenia_e_pocet, hodnotenia_fx_pocet, modifikovane,
                modifikoval, hromadna_zmena,
                pocet_kreditov, fakulta, podmienujuce_predmety,
                odporucane_predmety, vylucujuce_predmety, potrebny_jazyk,
                treba_zmenit_kod, predpokladany_semester) VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (
                    d['vahaSkusky'],
                    hodnotenia['A'],
                    hodnotenia['B'],
                    hodnotenia['C'],
                    hodnotenia['D'],
                    hodnotenia['E'],
                    hodnotenia['FX'],
                    datetime.datetime.strptime(d['datumSchvalenia'],"%d.%m.%Y"),
                    user,
                    True, # hromadna zmena
                    d['kredit'],
                    'FMFI',
                    u' '.join(podm_s_idckami),
                    '',
                    u' '.join(vyluc_s_idckami),
                    'sk_en',
                    False,
                    d['kodSemesterStudPlan']
                ))
            infolist_verzia_id = cur.fetchone()[0]
            
            suvisiace_predmety = set.union(podm_predmety, vyluc_predmety)
            for predmet_id in suvisiace_predmety:
              cur.execute('''INSERT INTO infolist_verzia_suvisiace_predmety
                (infolist_verzia, predmet) VALUES (%s, %s)''',
                (infolist_verzia_id, predmet_id))

            #if d['_C_']:
            #  vysledky_vzdelavania = u'''Tento obsah bol automaticky importovaný z položky "ciele predmetu", je potrebné ho zmeniť podľa požiadaviek na "výsledky vzdelávania"!\n\n'''
            #  vysledky_vzdelavania += d['_C_']
            #else:
            #  vysledky_vzdelavania = ''

            if d['_VV_']:
              vysledky_vzdelavania = d['_VV_']
            else:
              vysledky_vzdelavania = ''

            cur.execute('''INSERT INTO infolist_verzia_preklad
                    (infolist_verzia, jazyk_prekladu, nazov_predmetu, podm_absol_priebezne,
                    podm_absol_skuska, vysledky_vzdelavania,
                    strucna_osnova) VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (
                     infolist_verzia_id,
                     "sk",
                     d['nazov'],
                     d['_P_'],
                     d['_Z_'],
                     vysledky_vzdelavania,
                     d['_SO_'],
                    ))

            poradie = 1
            vlozeny = set()
            for vyucujuci in d['vyucujuciAll']:
                cur.execute('SELECT id FROM osoba WHERE cele_meno=%s',
                        (vyucujuci['plneMeno'], ))
                ids = cur.fetchall()
                if len(ids) > 1:
                    warn(u"Nasiel som duplikovany zaznam pre vyucujuceho %s na predmete %s"
                            % (vyucujuci['plneMeno'], d['kod']))
                    continue
                elif len(ids) == 0:
                    warn(u"Nenasiel som ziadny zaznam pre vyucujuceho %s na predmete %s"
                            % (vyucujuci['plneMeno'], d['kod']))
                    continue

                vyucujuci_id = ids[0]
                
                if vyucujuci_id not in vlozeny:
                    cur.execute('''INSERT INTO infolist_verzia_vyucujuci
                            (infolist_verzia, poradie, osoba)
                            VALUES (%s, %s, %s)
                            ''',
                            (infolist_verzia_id, poradie, vyucujuci_id))
                    vlozeny.add(vyucujuci_id)
                    poradie += 1

                # zabranit potencialnym duplikatom    
                cur.execute('''DELETE FROM infolist_verzia_vyucujuci_typ where
                        infolist_verzia=%s and osoba=%s 
                        and typ_vyucujuceho=%s''',
                        (infolist_verzia_id, vyucujuci_id, vyucujuci['typ']))
    
                cur.execute('''INSERT INTO infolist_verzia_vyucujuci_typ
                        (infolist_verzia, osoba, typ_vyucujuceho)
                        VALUES (%s, %s, %s)''',
                        (infolist_verzia_id, vyucujuci_id, vyucujuci['typ']))

            for sposob in d['sposoby']:
                cur.execute('''INSERT INTO infolist_verzia_cinnosti
                (infolist_verzia, metoda_vyucby, druh_cinnosti,
                pocet_hodin, za_obdobie) VALUES (%s, %s, %s, %s, %s)''',
                (
                    infolist_verzia_id,
                    d['metodaStudia'],
                    sposob['sposobVyucby'],
                    sposob['rozsahHodin'],
                    sposob['rozsahZaObdobie']
                ))
            
            cur.execute('''INSERT INTO infolist_verzia_literatura
              (infolist_verzia, bib_id, poradie)
              SELECT %s, bib_id, row_number() over ()
              FROM literatura_pre_import_predmetov
              WHERE kod_predmetu = %s''',
              (infolist_verzia_id, d['skratka']))

            cur.execute('''INSERT INTO infolist (posledna_verzia, import_z_aisu,
                    zamknute, zamkol, povodny_kod_predmetu)
                    VALUES (%s, %s, now(), %s, %s)
                    RETURNING id''',
                    (infolist_verzia_id, True, user, d['kod']))
            infolist_id = cur.fetchone()[0]
            
            predmet_id = vytvor_alebo_najdi_predmet(d['kod'], d['skratka'])
            
            cur.execute('''INSERT INTO predmet_infolist(predmet, infolist)
                           VALUES (%s, %s)''', (predmet_id, infolist_id))

def main(filenames, user, iba_kody=None, lang='sk', dry_run=False):
    with open(os.path.expanduser('~/.akreditacia.conn'), 'r') as f:
      conn_str = f.read()
    with closing(psycopg2.connect(conn_str)) as con:
        with con.cursor() as cur:
          cur.execute('SELECT id FROM osoba WHERE login = %s', (user,))
          row = cur.fetchone()
          if row == None:
            raise ValueError('Pouzivatel s loginom {} neexistuje'.format(user))
          user = row[0]
        for f in filenames:
            with context(subor=os.path.basename(f)):
                si = os.stat(f)
                if si.st_size == 0:
                  warn('Prekakujem prazdny subor {}'.format(os.path.basename(f)))
                  continue
                data = process_file(f, lang=lang)
                import2db(con, data, user, iba_kody=iba_kody, dry_run=dry_run)
        if not dry_run:
          con.commit()
    if not dry_run:
      print("Hotovo.")
    else:
      print("Hotovo. Kedze --dry-run, tak necommitujeme...")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Coverts AIS XMLs into HTMLs.')
    parser.add_argument('input_path', metavar='input-path', help='path to input XMLs')
    parser.add_argument('--lang', dest='lang', nargs='?', default='sk', help='language')
    parser.add_argument('--iba-kody', dest='iba_kody', metavar='kod',
      help='importujme iba IL pre predmety s kodom matchujucim tento regularny vyraz')
    parser.add_argument('user', help='user who makes the changes')
    parser.add_argument('--dry-run', help='do not commit the changes into DB', action='store_true')

    args = parser.parse_args()

    xml_path = os.path.join(args.input_path, '*.xml')
    filenames = glob.glob(xml_path)
    iba_kody = None
    if args.iba_kody:
      iba_kody = re.compile(args.iba_kody)
    
    main(filenames, args.user, iba_kody=iba_kody, lang=args.lang, dry_run=args.dry_run)

