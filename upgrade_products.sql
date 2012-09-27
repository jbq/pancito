INSERT INTO "product" (name, itemprice, creation_time) VALUES('Pain de 700 g', 400, '2012-05-17 19:33:57');
INSERT INTO "product" (name, itemprice, creation_time) VALUES('Pain de 1,4 kg', 800, '2012-05-17 19:34:05');
alter table user add column balance int not null default 0;
insert into bake (bakedate) values ('2012-11-01');
insert into bake (bakedate) values ('2012-11-08');
insert into bake (bakedate) values ('2012-11-15');
insert into bake (bakedate) values ('2012-11-22');
insert into bake (bakedate) values ('2012-11-29');
insert into bake (bakedate) values ('2012-12-06');
insert into bake (bakedate) values ('2012-12-13');
insert into bake (bakedate) values ('2012-12-20');
update bake set contract_id = 1 where rowid >=6;
alter table adhesion add column paperwork_verified datetime;

drop table contract;
CREATE TABLE contract (
    id integer primary key autoincrement not null,
    startdate date not null,
    enddate date not null,
    place text not null,
    timeslot text not null,
    creation_time datetime not null default current_timestamp
);
insert into contract(startdate, enddate, place, timeslot) values ('2012-10-04', '2012-12-20', 'au 20 avenue des Cottages 31400 Toulouse', 'le jeudi de 17h30 à 18h30');
