import logging
import datetime

import pytz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text


def get_db_data(metadata, engine, tables=None):
    ret = {}
    for table_name, v in metadata.tables.iteritems():
        if tables is not None and table_name not in tables:
            continue

        query = select([v]).order_by(*primary_keys(v))
        resp = engine.execute(query)

        rows = []
        keys = resp.keys()
        for row in resp:
            rows.append(dict((k, convert(row[k])) for k in keys))

        ret[table_name] = rows

    return ret


def delete_db_data(metadata, engine, tables):
    tables = list(tables)

    failed = True
    while failed:
        deleted_one = False
        failed = False
        for table_name in list(tables):
            table = metadata.tables[table_name]
            try:
                engine.execute(table.delete())
                tables.remove(table_name)
                deleted_one = True
            except IntegrityError as e:
                logging.info('Delete failed: %s, trying again', e)
                failed = True
        if not deleted_one:
            raise RuntimeError('Ran through all tables, could not delete any')


def set_db_data(metadata, engine, data):
    delete_db_data(metadata, engine, metadata.tables.keys())

    errs = []
    failed = True
    while failed:
        inserted_one = False
        failed = False
        for table_name, table_data in data.items():
            with engine.begin() as trans:
                try:
                    for row in table_data:
                        keys = ','.join(row.keys())
                        values = ','.join([':' + k for k in row.keys()])
                        query = 'INSERT INTO %s (%s) VALUES (%s)' % (table_name,
                                                                     keys,
                                                                     values)
                        trans.execute(text(query), **row)
                    inserted_one = True
                    del data[table_name]
                except IntegrityError as e:
                    errs.append('Insert failed: %s, trying again' % e)
                    failed = True
        if not inserted_one:
            for e in errs:
                logging.info(e)
            raise RuntimeError('Ran through all tables, inserts still failed')

    if engine.name == 'postgresql':
        _pg_fix_sequences(engine)


def _pg_fix_sequences(engine):
    """
    Fix sequences so they won't conflict. This query generates queries that
    will fix the sequences for all tables. Taken from:
    https://wiki.postgresql.org/wiki/Fixing_Sequences
    """

    query_generator = """
        SELECT 'SELECT SETVAL(' ||
               quote_literal(quote_ident(PGT.schemaname) || '.' || quote_ident(S.relname)) ||
               ', MAX(' ||quote_ident(C.attname)|| ') ) FROM ' ||
               quote_ident(PGT.schemaname)|| '.'||quote_ident(T.relname)|| ';'
        FROM pg_class AS S,
             pg_depend AS D,
             pg_class AS T,
             pg_attribute AS C,
             pg_tables AS PGT
        WHERE S.relkind = 'S'
            AND S.oid = D.objid
            AND D.refobjid = T.oid
            AND D.refobjid = C.attrelid
            AND D.refobjsubid = C.attnum
            AND T.relname = PGT.tablename
        ORDER BY S.relname;
    """
    with engine.begin() as trans:
        queries = list(trans.execute(text(query_generator)))
        for q in queries:
            trans.execute(text(q[0]))


def convert(item):
    if item is None:
        return None

    if isinstance(item, (float, int)):
        return item

    # convert datetime to UTC before serializing it
    if isinstance(item, datetime.datetime) and item.tzinfo is not None:
        item = item.astimezone(pytz.utc)

    if isinstance(item, (datetime.date, datetime.datetime)):
        return item.isoformat()

    if hasattr(item, '__sqlvalue__'):
        return item.__sqlvalue__()

    return unicode(item)


def primary_keys(tabledata):
    return [c for c in tabledata.columns.values() if c.primary_key]
