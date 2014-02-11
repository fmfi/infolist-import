BEGIN;

CREATE TABLE literatura_pre_import_predmetov (
  kod_predmetu varchar(50) not null,
  bib_id integer not null,
  primary key(kod_predmetu, bib_id)
);

COMMIT;