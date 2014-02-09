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

def process_file(filename, lang='sk'):
    xmldoc = ET.parse(filename)
    root = xmldoc.getroot()
    organizacnaJednotka = root.find('organizacnaJednotka').text
    ilisty = root.find('informacneListy')
    print("Nasiel som %d informacnych listov." %
            len(ilisty.findall('informacnyList')))

    # elementy, ktore sa budu parsovat z XML-ka
    elements = ('kod', 'skratka', 'nazov', 'kredit', 'sposobUkoncenia', 'sposobVyucby',
                'rozsahTyzdenny', 'rozsahSemestranly', 'obdobie', 'rokRocnikStudPlan',
                'kodSemesterStudPlan', 'jazyk', 'podmienujucePredmety', 'metodyStudia',
                'vyucujuciAll', 'zabezpecuju', 'datumSchvalenia', '_VH_', '_SO_', '_C_',
                '_Z_', '_P_', '_O_', '_S_', 'vylucujucePredmety',
                'hodnoteniaPredmetu')

    map_metodyStudia = {u'prezenčná': 'P', u'dištančná': 'D', u'kombinovaná': 'K'}
    # vid ciselnik druh_cinnosti
    map_sposobVyucby = {u'Prednáška': 'P', u'Cvičenie': 'C', u'Samostatná práca': 'D',
      u'Kurz': 'K', u'Iná': 'I', u'Práce v teréne': 'T', u'Seminár': 'S',
      u'Laboratórne cvičenie': 'L', u'Prax': 'X', u'sústredenie': 'U'}

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
                        d[e] = ET.tostring(il.find(e).find('texty/*'))
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
                    d['hodnoteniaPredmetu'] = {}
                    s = 0
                    for hodnotenie in il.find(e).findall('hodnoteniePredmetu'):
                        d['hodnoteniaPredmetu'][hodnotenie.find('kod').text] =\
                        {
                            'pocetHodnoteni': hodnotenie.find('pocetHodnoteni').text,
                            'percentualneVyjadrenieZCelkPoctuHodnoteni': hodnotenie.find('percentualneVyjadrenieZCelkPoctuHodnoteni').text
                        }
                        s += int(hodnotenie.find('pocetHodnoteni').text)
                    assert(s == int(d['celkovyPocetHodnotenychStudentov']))
                elif e == 'metodyStudia':
                    metodyStudia = il.find(e).findall('metodaStudia')
                    assert(len(metodyStudia) == 1)
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
                      if rozsahTyzdenny[i] != None:
                        hodin = rozsahTyzdenny[i]
                        za_obdobie = 'T'
                      else:
                        hodin = rozsahSemestranly[i]
                        za_obdobie = 'S'
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

        data.append(d)

    return data

def import2db(con, data):
    """ import do cistej db"""
    with closing(con.cursor()) as cur:
        for d in data:
            # checkni duplikaty
            cur.execute('SELECT 1 FROM predmet WHERE kod_predmetu=%s',
                    (d['kod'],))
            is_duplicate = cur.fetchone() != None
            if is_duplicate:
                warn(u"Duplikovany zaznam pre predmet %s" % d['kod'])
                continue

            hodnotenia = {}
            for hodn in ['A', 'B', 'C', 'D', 'E', 'FX']:
              if 'hodnoteniaPredmetu' in d and hodn in d['hodnoteniaPredmetu']:
                hodnotenia[hodn] = d['hodnoteniaPredmetu'][hodn]['pocetHodnoteni']
              else:
                hodnotenia[hodn] = None

            cur.execute('''INSERT INTO infolist_verzia (
                podm_absol_percenta_skuska, hodnotenia_a_pocet,
                hodnotenia_b_pocet, hodnotenia_c_pocet, hodnotenia_d_pocet,
                hodnotenia_e_pocet, hodnotenia_fx_pocet, modifikovane,
                pocet_kreditov, fakulta) VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''',
                (
                    d['vahaSkusky'],
                    hodnotenia['A'],
                    hodnotenia['B'],
                    hodnotenia['C'],
                    hodnotenia['D'],
                    hodnotenia['E'],
                    hodnotenia['FX'],
                    datetime.datetime.strptime(d['datumSchvalenia'],"%d.%m.%Y"),
                    d['kredit'],
                    'FMFI'
                ))
            infolist_verzia_id = cur.fetchone()[0]

            cur.execute('''INSERT INTO infolist_verzia_preklad
                    (infolist_verzia, jazyk_prekladu, nazov_predmetu, podm_absol_priebezne,
                    podm_absol_skuska, vysledky_vzdelavania,
                    strucna_osnova, potrebny_jazyk) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                    (
                     infolist_verzia_id,
                     "sk",
                     d['nazov'],
                     d['_P_'],
                     d['_Z_'],
                     d['_C_'],
                     d['_SO_'],
                     None,
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
                            VALUES (%s, %s, %s)''',
                            (infolist_verzia_id, poradie, vyucujuci_id))
                    vlozeny.add(vyucujuci_id)
                    poradie += 1
                
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

            cur.execute('''INSERT INTO infolist (posledna_verzia, import_z_aisu,
                    zamknute) VALUES (%s, %s, %s) RETURNING id''',
                    (infolist_verzia_id, True, False))
            infolist_id = cur.fetchone()[0]
            
            cur.execute('''INSERT INTO predmet (kod_predmetu, skratka) VALUES (%s, %s)
                        RETURNING id''',
                        (d['kod'], d['skratka']))
            predmet_id = cur.fetchone()[0]
            
            cur.execute('''INSERT INTO predmet_infolist(predmet, infolist)
                           VALUES (%s, %s)''', (predmet_id, infolist_id))


def main(filenames, lang='sk'):
    with open(os.path.expanduser('~/.akreditacia.conn'), 'r') as f:
      conn_str = f.read()
    with closing(psycopg2.connect(conn_str)) as con:
        for f in filenames:
            print("Spracuvam subor '%s'..." % f)
            with context(subor=os.path.basename(f)):
                data = process_file(f, lang=lang)
                import2db(con, data)
        con.commit()
    print("Hotovo.")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description='Coverts AIS XMLs into HTMLs.')
    parser.add_argument('input_path', metavar='input-path', help='path to input XMLs')
    parser.add_argument('--lang', dest='lang', nargs='?', default='sk', help='language')

    args = parser.parse_args()

    xml_path = os.path.join(args.input_path, '*.xml')
    filenames = glob.glob(xml_path)
    main(filenames, lang=args.lang)

