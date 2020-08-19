# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import psycopg2

_schema = logging.getLogger('odoo.schema')

_TABLE_KIND = {
    'BASE TABLE': 'r',
    'VIEW': 'v',
    'FOREIGN TABLE': 'f',
    'LOCAL TEMPORARY': 't',
}

_CONFDELTYPES = {
    'RESTRICT': 'r',
    'NO ACTION': 'a',
    'CASCADE': 'c',
    'SET NULL': 'n',
    'SET DEFAULT': 'd',
}

def existing_tables(cr, tablenames):
    """ Return the names of existing tables among ``tablenames``. """
    query = """
        SELECT c.relname
          FROM pg_class c
          JOIN pg_namespace n ON (n.oid = c.relnamespace)
         WHERE c.relname IN %s
           AND c.relkind IN ('r', 'v', 'm')
           AND n.nspname = 'public'
    """
    cr.execute(query, [tuple(tablenames)])
    return [row[0] for row in cr.fetchall()]

def table_exists(cr, tablename):
    """ Return whether the given table exists. """
    return len(existing_tables(cr, {tablename})) == 1

def table_kind(cr, tablename):
    """ Return the kind of a table: ``'r'`` (regular table), ``'v'`` (view),
        ``'f'`` (foreign table), ``'t'`` (temporary table), or ``None``.
    """
    query = "SELECT table_type FROM information_schema.tables WHERE table_name=%s"
    cr.execute(query, (tablename,))
    return _TABLE_KIND[cr.fetchone()[0]] if cr.rowcount else None

def create_model_table(cr, tablename, comment=None, bigint=False):
    """ Create the table for a model. """
    cr.execute('CREATE TABLE "{}" (id {} NOT NULL, PRIMARY KEY(id))'.format(
        tablename, 'BIGSERIAL' if bigint else 'SERIAL'))
    if comment:
        cr.execute('COMMENT ON TABLE "{}" IS %s'.format(tablename), (comment,))
    _schema.debug("Table %r: created", tablename)

def table_columns(cr, tablename):
    """ Return a dict mapping column names to their configuration. The latter is
        a dict with the data from the table ``information_schema.columns``.
    """
    # Do not select the field `character_octet_length` from `information_schema.columns`
    # because specific access right restriction in the context of shared hosting (Heroku, OVH, ...)
    # might prevent a postgres user to read this field.
    query = '''SELECT column_name, udt_name, character_maximum_length, is_nullable
               FROM information_schema.columns WHERE table_name=%s'''
    cr.execute(query, (tablename,))
    return {row['column_name']: row for row in cr.dictfetchall()}

def column_type(cr, table, column):
    """ Return the sql column type """
    cr.execute(
        """ SELECT udt_name FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s """, (table, column))
    row = cr.fetchone()
    return row[0] if row else None

def column_exists(cr, tablename, columnname):
    """ Return whether the given column exists. """
    query = """ SELECT 1 FROM information_schema.columns
                WHERE table_name=%s AND column_name=%s """
    cr.execute(query, (tablename, columnname))
    return cr.rowcount

def create_column(cr, tablename, columnname, columntype, comment=None):
    """ Create a column with the given type. """
    cr.execute('ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(tablename, columnname, columntype))
    if comment:
        cr.execute('COMMENT ON COLUMN "{}"."{}" IS %s'.format(tablename, columnname), (comment,))
    _schema.debug("Table %r: added column %r of type %s", tablename, columnname, columntype)

def rename_column(cr, tablename, columnname1, columnname2):
    """ Rename the given column. """
    cr.execute('ALTER TABLE "{}" RENAME COLUMN "{}" TO "{}"'.format(tablename, columnname1, columnname2))
    _schema.debug("Table %r: renamed column %r to %r", tablename, columnname1, columnname2)

def convert_column(cr, tablename, columnname, columntype):
    """ Convert the column to the given type. """
    converted = False
    if columntype == 'int8' and column_type(cr, tablename, columnname) == 'int4':
        convert_column_int4_to_int8(cr, tablename, columnname)
        converted = True
    if not converted:
        try:
            with cr.savepoint():
                cr.execute('ALTER TABLE "{}" ALTER COLUMN "{}" TYPE {}'.format(
                    tablename, columnname, columntype), log_exceptions=False)
                converted = True
        except psycopg2.NotSupportedError:
            pass
    if not converted:
        # can't do inplace change -> use a casted temp column
        query = '''
            ALTER TABLE "{0}" RENAME COLUMN "{1}" TO __temp_type_cast;
            ALTER TABLE "{0}" ADD COLUMN "{1}" {2};
            UPDATE "{0}" SET "{1}"= __temp_type_cast::{2};
            ALTER TABLE "{0}" DROP COLUMN  __temp_type_cast CASCADE;
        '''
        cr.execute(query.format(tablename, columnname, columntype))
        converted = True
    _schema.debug("Table %r: column %r changed to type %s", tablename, columnname, columntype)

def set_not_null(cr, tablename, columnname):
    """ Add a NOT NULL constraint on the given column. """
    query = 'ALTER TABLE "{}" ALTER COLUMN "{}" SET NOT NULL'.format(tablename, columnname)
    try:
        with cr.savepoint():
            cr.execute(query)
            _schema.debug("Table %r: column %r: added constraint NOT NULL", tablename, columnname)
    except Exception:
        msg = "Table %r: unable to set NOT NULL on column %r!\n" \
              "If you want to have it, you should update the records and execute manually:\n%s"
        _schema.warning(msg, tablename, columnname, query, exc_info=True)

def drop_not_null(cr, tablename, columnname):
    """ Drop the NOT NULL constraint on the given column. """
    cr.execute('ALTER TABLE "{}" ALTER COLUMN "{}" DROP NOT NULL'.format(tablename, columnname))
    _schema.debug("Table %r: column %r: dropped constraint NOT NULL", tablename, columnname)

def constraint_definition(cr, tablename, constraintname):
    """ Return the given constraint's definition. """
    query = """
        SELECT COALESCE(d.description, pg_get_constraintdef(c.oid))
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        LEFT JOIN pg_description d ON c.oid = d.objoid
        WHERE t.relname = %s AND conname = %s;"""
    cr.execute(query, (tablename, constraintname))
    return cr.fetchone()[0] if cr.rowcount else None

def add_constraint(cr, tablename, constraintname, definition):
    """ Add a constraint on the given table. """
    query1 = 'ALTER TABLE "{}" ADD CONSTRAINT "{}" {}'.format(tablename, constraintname, definition)
    query2 = 'COMMENT ON CONSTRAINT "{}" ON "{}" IS %s'.format(constraintname, tablename)
    try:
        with cr.savepoint():
            cr.execute(query1)
            cr.execute(query2, (definition,))
            _schema.debug("Table %r: added constraint %r as %s", tablename, constraintname, definition)
    except Exception:
        msg = "Table %r: unable to add constraint %r!\n" \
              "If you want to have it, you should update the records and execute manually:\n%s"
        _schema.warning(msg, tablename, constraintname, query1, exc_info=True)

def drop_constraint(cr, tablename, constraintname):
    """ drop the given constraint. """
    try:
        with cr.savepoint():
            cr.execute('ALTER TABLE "{}" DROP CONSTRAINT "{}"'.format(tablename, constraintname))
            _schema.debug("Table %r: dropped constraint %r", tablename, constraintname)
    except Exception:
        _schema.warning("Table %r: unable to drop constraint %r!", tablename, constraintname)

def add_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete):
    """ Create the given foreign key, and return ``True``. """
    query = 'ALTER TABLE "{}" ADD FOREIGN KEY ("{}") REFERENCES "{}"("{}") ON DELETE {}'
    cr.execute(query.format(tablename1, columnname1, tablename2, columnname2, ondelete))
    _schema.debug("Table %r: added foreign key %r references %r(%r) ON DELETE %s",
                  tablename1, columnname1, tablename2, columnname2, ondelete)
    return True

def fix_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete):
    """ Update the foreign keys between tables to match the given one, and
        return ``True`` if the given foreign key has been recreated.
    """
    # Do not use 'information_schema' here, as those views are awfully slow!
    deltype = _CONFDELTYPES.get(ondelete.upper(), 'a')
    query = """ SELECT con.conname, c2.relname, a2.attname, con.confdeltype as deltype
                  FROM pg_constraint as con, pg_class as c1, pg_class as c2,
                       pg_attribute as a1, pg_attribute as a2
                 WHERE con.contype='f' AND con.conrelid=c1.oid AND con.confrelid=c2.oid
                   AND array_lower(con.conkey, 1)=1 AND con.conkey[1]=a1.attnum
                   AND array_lower(con.confkey, 1)=1 AND con.confkey[1]=a2.attnum
                   AND a1.attrelid=c1.oid AND a2.attrelid=c2.oid
                   AND c1.relname=%s AND a1.attname=%s """
    cr.execute(query, (tablename1, columnname1))
    found = False
    for fk in cr.fetchall():
        if not found and fk[1:] == (tablename2, columnname2, deltype):
            found = True
        else:
            drop_constraint(cr, tablename1, fk[0])
    if not found:
        return add_foreign_key(cr, tablename1, columnname1, tablename2, columnname2, ondelete)

def index_exists(cr, indexname):
    """ Return whether the given index exists. """
    cr.execute("SELECT 1 FROM pg_indexes WHERE indexname=%s", (indexname,))
    return cr.rowcount

def create_index(cr, indexname, tablename, expressions):
    """ Create the given index unless it exists. """
    if index_exists(cr, indexname):
        return
    args = ', '.join(expressions)
    cr.execute('CREATE INDEX "{}" ON "{}" ({})'.format(indexname, tablename, args))
    _schema.debug("Table %r: created index %r (%s)", tablename, indexname, args)

def create_unique_index(cr, indexname, tablename, expressions):
    """ Create the given index unless it exists. """
    if index_exists(cr, indexname):
        return
    args = ', '.join(expressions)
    cr.execute('CREATE UNIQUE INDEX "{}" ON "{}" ({})'.format(indexname, tablename, args))
    _schema.debug("Table %r: created index %r (%s)", tablename, indexname, args)

def drop_index(cr, indexname, tablename):
    """ Drop the given index if it exists. """
    cr.execute('DROP INDEX IF EXISTS "{}"'.format(indexname))
    _schema.debug("Table %r: dropped index %r", tablename, indexname)

def drop_view_if_exists(cr, viewname):
    cr.execute("DROP view IF EXISTS %s CASCADE" % (viewname,))

def escape_psql(to_escape):
    return to_escape.replace('\\', r'\\').replace('%', '\%').replace('_', '\_')

def pg_varchar(size=0):
    """ Returns the VARCHAR declaration for the provided size:

    * If no size (or an empty or negative size is provided) return an
      'infinite' VARCHAR
    * Otherwise return a VARCHAR(n)

    :type int size: varchar size, optional
    :rtype: str
    """
    if size:
        if not isinstance(size, int):
            raise ValueError("VARCHAR parameter should be an int, got %s" % type(size))
        if size > 0:
            return 'VARCHAR(%d)' % size
    return 'VARCHAR'

def reverse_order(order):
    """ Reverse an ORDER BY clause """
    items = []
    for item in order.split(','):
        item = item.lower().split()
        direction = 'asc' if item[1:] == ['desc'] else 'desc'
        items.append('%s %s' % (item[0], direction))
    return ', '.join(items)

def get_indexes(cr, table, column):
    """ Get the indexes that are based on the given column.
    Exclude indexes owned by a constraint, as dropping the constraint will
    also drop the index. """
    cr.execute(
        """
        SELECT tbl.relname AS table_name,
            pgis.indexname,
            pgis.indexdef
        FROM pg_class tbl
        JOIN pg_index pgi ON pgi.indrelid = tbl.oid
        JOIN pg_class idx ON pgi.indexrelid = idx.oid
        JOIN pg_attribute pga ON pga.attrelid = tbl.oid
        JOIN pg_indexes pgis ON pgis.indexname = idx.relname
            AND pgis.tablename = tbl.relname
        WHERE tbl.relkind = 'r'
            AND pga.attname = %s
            AND pga.attnum = ANY(pgi.indkey)
            AND tbl.relname = %s
            AND NOT EXISTS(
                SELECT * FROM pg_constraint WHERE conindid = pgi.indexrelid)
        """, (column, table))
    return set(cr.fetchall())

def get_fk_constraints(cr, table, column):
    """ Get the FK constraints that are based on the given column. """
    cr.execute(
        """
        SELECT kcu.table_name, kcu.column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_schema = kcu.constraint_schema
                AND tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_schema = tc.constraint_schema
                AND ccu.constraint_name = tc.constraint_name
        JOIN pg_constraint pgc
            ON pgc.conname = tc.constraint_name
                AND tc.table_name = pgc.conrelid::regclass::text
        WHERE ccu.table_name = %s
            AND ccu.column_name = %s
            AND constraint_type = 'FOREIGN KEY'
        """, (table, column))
    return cr.fetchall()

def get_views(cr, table, column):
    """ Get the views that are based on the given column """
    cr.execute(
        """
        SELECT pgc.oid::regclass AS view,
        pgv.definition
        FROM pg_attribute AS pga
        JOIN pg_depend AS pgd
            ON pgd.refobjsubid = pga.attnum AND pgd.refobjid = pga.attrelid
        JOIN pg_rewrite AS pgr
            ON pgr.oid = pgd.objid
        JOIN pg_class AS pgc
            ON pgc.oid = pgr.ev_class
        JOIN pg_views pgv
            ON pgv.viewname = pgc.oid::regclass::text
        WHERE pgc.relkind = 'v'
            AND pgd.classid = 'pg_rewrite'::regclass
            AND pgd.refclassid = 'pg_class'::regclass
            AND pgd.deptype = 'n'
            AND pga.attrelid = %s::regclass
            AND pga.attname = %s;
        """, (table, column))
    return [row for row in cr.fetchall()]

def convert_column_int4_to_int8(cr, table, column):
    """ Migrate an INTEGER column, and its FK reference columns recursively,
    to a BIGINT column. Attempts to let Postgres change the column type,
    with a fallback on creating a new column and copying over the data.

    Postgresql supports changing the column type, but only if there are no
    dependent views so we drop and recreate those later. """
    logger = logging.getLogger('openerp.tools.sql.int4_to_int8.%s.%s' % (table, column))

    constraints = get_fk_constraints(cr, table, column)
    views = get_views(cr, table, column)

    for view in views:
        logger.info('dropping view "%s"', view[0])
        cr.execute('DROP VIEW "%s"' % view[0])

    logger.info('Changing column type to int8')
    cr.execute('ALTER TABLE "{}" ALTER COLUMN "{}" TYPE {}'.format(
        table, column, 'int8'), log_exceptions=False)

    for constraint in constraints:
        # Call this code recursively on any column with an FK constaint
        # on this one (and before we drop the PK constraint)
        convert_column_int4_to_int8(cr, constraint[0], constraint[1])

    if column == 'id':
        # Update sequence to BIGINT. Before Postgres 10.0, sequences were BIGINT by default
        # and the 'AS BIGINT' syntax is not supported
        if cr._cnx.server_version >= 100000:
            cr.execute('ALTER SEQUENCE IF EXISTS %s_%s_seq '
                       'AS BIGINT' % (table, column))

    for view in views:
        logger.info('recreating view "%s"', view[0])
        cr.execute('CREATE VIEW "%s" AS %s' % view)
