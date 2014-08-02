# Import infolistov z AIS-u do databázy editora infolistov

## Inštalácia

```bash
sudo apt-get install libxml2-dev libxslt-dev zlib1g-dev

cd /home/ka
git clone https://github.com/fmfi/infolist-import.git
cd infolist-import
virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Stiahnutie infolistov

Na stiahnutie infolistov sa používa projekt [ais-infolisty](https://github.com/fmfi-svt/ais-infolisty).

```bash
cd /home/ka
mkdir ais-infolisty-data # sem chceme stiahnut XML data infolistov z AIS-u
git clone https://github.com/fmfi-svt/ais-infolisty.git
cd ais-infolisty
./update_infolists.py --download-only --data-dir=/home/ka/ais-infolisty-data
```

## Priradenie literatúry k predmetom

Literatúra sa k predmetu automaticky priradí z tabuľky `literatura_pre_import_predmetov`.

Ak táto tabuľka neexistuje, vytvorme ju:

```bash
cd /home/ka/ais-infolisty
sudo -u ka psql akreditacia <db-schema.sql
```

Túto tabuľku teraz treba naplniť (ak ostane prázdna, žiadna literatúra sa nepriradí).

## Import infolistov

Ak ešte nemáme súbor s nastaveniami db, vytvorme ho:

```bash
echo 'host=localhost dbname=akreditacia user=ka password=changeit' >~/.akreditacia.conn
chmod go= ~/.akreditacia.conn
```

A naimportujme dáta (program importuje iba predmety, ktoré ešte neboli naimportované):

```bash
cd /home/ka/ais-infolisty
./import.py /home/ka/ais-infolisty-data/FMFI/xml_files_sk/ hrasko47
```

Kde `hrasko47` je login administratora systemu (zaznaci sa ako osoba vykonavajuca zmeny).

> Poznámka: Ak cheme importovať iba niektoré predmety, môžme zadať regulárny výraz,
> podľa ktorého sa majú filtrovať kódy predmetov, do argumentu `--iba-kody`.



> Poznámka: Ak chceme iba vidieť, čo by sa robilo bez reálneho importu dát, môžme použiť
> argument `--dry-run`, ktorý spôsobí, že sa na konci necommitnú dáta.