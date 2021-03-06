import logging
import logging.config
from feature_utils import make_inspections_address_nmonths_table, compute_frequency_features
from feature_utils import format_column_names, group_and_count_from_db, load_colpivot, \
                            make_table_of_frequent_codes
from lib_cinci.config import load
from lib_cinci.features import check_date_boundaries
from psycopg2 import ProgrammingError, InternalError
import pandas as pd

#Config logger
logging.config.dictConfig(load('logger_config.yaml'))
logger = logging.getLogger()

def make_permits_features(con, n_months, max_dist):
    """
    Make permits features

    Input:
    db_connection: connection to postgres database.
                   "set schema ..." must have been called on this connection
                   to select the correct schema from which to load inspections

    Output:
    A pandas dataframe, with one row per inspection and one column per feature.
    """
    dataset = 'permits'
    date_column = 'issueddate'

    load_colpivot(con)

    #Get the time window for which you can generate features
    min_insp, max_insp = check_date_boundaries(con, n_months, dataset, date_column)

    make_inspections_address_nmonths_table(con, dataset, date_column,
        min_insp, max_insp, n_months=n_months, max_dist=max_dist, load=False)
    
    logger.info('Computing distance features for {}'.format(dataset))

    cur = con.cursor()

    insp2tablename = ('insp2{dataset}_{n_months}months'
                  '_{max_dist}m').format(dataset='permits',
                                         n_months=str(n_months),
                                         max_dist=str(max_dist))

    # create a table of the most common proposeduse types,
    # so we can limit the pivot later to the 15 most common
    # types of uses
    cols = ['proposeduse',
            'statuscurrent',
            'workclass',
            'permitclass',
            'permittype'
            ]

    coalescemissing = "'missing'" 

    for col in cols:
        make_table_of_frequent_codes(con, col=col, intable='public.permits',
                outtable='public.frequentpermit_%s'%col, rnum=15,
                coalesce_to=coalescemissing)

    unionall_template = """
        SELECT parcel_id, inspection_date, 
              '{col}_'||coalesce(t2.level,{coalescemissing}) as categ,
              coalesce(t1.count, 0) as count
        FROM (
            SELECT parcel_id, inspection_date,
                   fs.level,
                   count(*) as count
            FROM joinedpermits_{n_months}months_{max_dist}m event
            LEFT JOIN public.frequentpermit_{col} fs
            ON fs.raw_level = coalesce(event.{col},{coalescemissing})
            GROUP BY parcel_id, inspection_date, fs.level
        ) t1
        RIGHT JOIN (
            SELECT parcel_id, inspection_date, t.level
            FROM parcels_inspections
            JOIN ( SELECT distinct level FROM public.frequentpermit_{col} ) t
            ON true
        ) t2
        USING (parcel_id, inspection_date, level)
        """

    unionall_statements = unionall_template.format(col=cols[0],
                                                  n_months=str(n_months),
                                                  max_dist=str(max_dist),
                                                  coalescemissing=coalescemissing
                                                  ) + \
                          '\n'.join([
                            'UNION ALL ( %s )'%unionall_template.format(col=col,
                                                                        n_months=str(n_months),
                                                                        max_dist=str(max_dist),
                                                                        coalescemissing=coalescemissing
                                                                        )
                            for col in cols[1:]
                            ])

    cur = con.cursor()
    query = """
        DROP TABLE IF EXISTS permitfeatures1_{n_months}months_{max_dist}m;

        CREATE TEMP TABLE permitfeatures1_{n_months}months_{max_dist}m ON COMMIT DROP AS
            SELECT 
                parcel_id,
                inspection_date,
                count(*) as total,
                avg(completeddate-applieddate) as avg_days_applied_to_completed,
                avg(completeddate-issueddate) as avg_days_issued_to_completed,
                avg(issueddate-applieddate) as avg_days_applied_to_issued,
                avg(expiresdate-issueddate) as avg_days_issued_to_expires,
                avg(expiresdate-completeddate) as avg_days_completed_to_expires,
                avg(CASE WHEN issueddate IS NOT NULL THEN 1 ELSE 0 END) as avg_issued,
                avg(CASE WHEN completeddate IS NOT NULL THEN 1 ELSE 0 END) as avg_completed,
                avg(CASE WHEN expiresdate IS NOT NULL THEN 1 ELSE 0 END) as avg_expires,
                avg(totalsqft) as avg_sqft,
                avg(estprojectcostdec) as avg_estcost,
                avg(units) as avg_units,
                avg(CASE WHEN coissueddate IS NOT NULL THEN 1 ELSE 0 END) as avg_is_coissued,
                avg(substring(fee from 2)::real) as avg_fee,
                avg(CASE WHEN companyname='OWNER' THEN 1 ELSE 0 END) as avg_owner_is_company
            FROM insp2permits_{n_months}months_{max_dist}m i2e
            LEFT JOIN public.permits event USING (id)
            GROUP BY parcel_id, inspection_date;
        CREATE INDEX ON permitfeatures1_{n_months}months_{max_dist}m (parcel_id, inspection_date);

        -- make the categorical (dummified) features 
        CREATE TEMP TABLE joinedpermits_{n_months}months_{max_dist}m ON COMMIT DROP AS
            SELECT parcel_id, inspection_date, event.* 
            FROM insp2permits_{n_months}months_{max_dist}m i2e
            LEFT JOIN LATERAL (
                SELECT * FROM public.permits s where s.id=i2e.id
            ) event
            ON true
        ;
        CREATE INDEX ON joinedpermits_{n_months}months_{max_dist}m (parcel_id, inspection_date);

        -- Join the permits with the inspections; then concatenate the 
        -- inspections and the various categorical variables (we'll pivot later)
        
        CREATE TEMP TABLE permitfeatures2_{n_months}months_{max_dist}m ON COMMIT DROP AS

            {unionall_statements};

        CREATE INDEX ON permitfeatures2_{n_months}months_{max_dist}m (parcel_id, inspection_date);

        -- Now call the pivot function to create columns with the 
        -- different fire types
        SELECT colpivot('permitpivot_{n_months}months_{max_dist}m',
                        'select * from permitfeatures2_{n_months}months_{max_dist}m',
                        array['parcel_id','inspection_date'],
                        array['categ'],
                        'coalesce(#.count,0)',
                        null
        );
        CREATE INDEX ON permitpivot_{n_months}months_{max_dist}m (parcel_id, inspection_date);

        -- still need to 'save' the tables into a permanent table
        CREATE TABLE permitfeatures_{n_months}months_{max_dist}m AS
            SELECT * FROM permitfeatures1_{n_months}months_{max_dist}m
            JOIN permitpivot_{n_months}months_{max_dist}m
            USING (parcel_id, inspection_date)
        ;
    """.format(n_months=str(n_months), max_dist=str(max_dist), unionall_statements=unionall_statements)

    cur.execute(query)
    con.commit()
    
    # fetch the data
    query = """
        SELECT * FROM permitfeatures_{n_months}months_{max_dist}m;
    """.format(n_months=str(n_months),
               max_dist=str(max_dist))

    df = pd.read_sql(query, con, index_col=['parcel_id', 'inspection_date'])

    # clean up the column names
    df.columns = map(lambda x: x.replace(' ','_').lower(), df.columns)
    df.columns = map(lambda x: ''.join(c for c in x if c.isalnum() or c=='_'),
                    df.columns)

    # drop the last interim table
    query = 'drop table permitfeatures_{n_months}months_{max_dist}m'.format(
            n_months=str(n_months), max_dist=str(max_dist))
    cur.execute(query)
    con.commit()

    return df

