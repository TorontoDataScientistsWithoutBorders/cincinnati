#!/usr/bin/env python
import datetime
import logging
import logging.config
from collections import namedtuple
import argparse

import pandas as pd
import psycopg2
from sqlalchemy import create_engine
from sqlalchemy import types

from lib_cinci.config import main as main_cfg
from lib_cinci.db import uri
from lib_cinci.config import load

from lib_cinci.exceptions import MaxDateError, NoFeaturesSelected
from lib_cinci.features import existing_feature_schemas, tables_in_schema

#Features
import ner, parcel, outcome, tax, crime_agg, census, three11
import fire, permits, crime, sales, violation_density, weather, quarter

logging.config.dictConfig(load('logger_config.yaml'))
logger = logging.getLogger()

# for every feature-set to generate, you need to register a function
# that can generate a dataframe containing the
# new features. you also need to set the database table in
# which to store the features
FeatureToGenerate = namedtuple("FeatureToGenerate",
                               ["table", "generator_function"])

# list all existing feature-sets
existing_features = [FeatureToGenerate("tax", tax.make_tax_features),
                         # Deprecated - data schema changed in the spring 2016 update
                         # FeatureToGenerate("crime_agg", crime_agg.make_crime_features),
                         FeatureToGenerate("named_entities",
                                           ner.make_owner_features),
                         FeatureToGenerate("house_type",
                                           parcel.make_house_type_features),
                         FeatureToGenerate("parc_area",
                                           parcel.make_size_of_prop),
                         FeatureToGenerate("parc_year",
                                           parcel.make_year_built),
                         FeatureToGenerate("census_2010",
                                           census.make_census_features),
                         FeatureToGenerate("three11",
                                           three11.make_three11_features),
                         FeatureToGenerate("permits",
                                           permits.make_permits_features),
                         FeatureToGenerate("crime",
                                           crime.make_crime_features),
                         FeatureToGenerate("fire",
                                           fire.make_fire_features),
                         FeatureToGenerate("sales",
                                           sales.make_sales_features),
                         FeatureToGenerate("density",
                                           violation_density.make_inspections_features),
                         FeatureToGenerate("quarter",
                                           quarter.make_quarter_features),
                         FeatureToGenerate("sixweeksweather",
                                           weather.make_weather_features)]

def generate_features(features_to_generate, n_months, max_dist,
                     inspection_date=None, insp_set='all_inspections'):
    """
    Generate labels and features for all inspections
    in the inspections database.

    If inspection_date is passed, features will be generated as if
    an inspection will occur on that day
    """
    #select schema
    #depending on the value of inspection date
    
    if insp_set=='all_inspections':
      if inspection_date is None:
        schema = "features"
      else:
        schema = "features_{}".format(inspection_date.strftime('%d%b%Y')).lower()
    elif insp_set=='field_test':
      if inspection_date is None:
        schema = "features_field_test"
      else:
        schema = "features_field_test_{}".format(inspection_date.strftime('%d%b%Y')).lower()

    # use this engine for all data storing (somehow does
    # not work with the raw connection we create below)
    engine = create_engine(uri)

    # all querying is done using a raw connection. in this
    # connection set to use the relevant schema
    # this makes sure that we grab the "inspections_parcels"
    # table from the correct schema in all feature creators
    con = engine.raw_connection()
    # con = engine.connect()

    if schema not in existing_feature_schemas():
        #Create schema here
        cur = con.cursor()
        cur.execute("CREATE  SCHEMA %s;" % schema)
        con.commit()
        cur.close()
        logging.info('Creating schema %s' % schema)
    else:
        logging.info('Using existing schema')

    #Note on SQL injection: schema is either features or features_DATE
    #date is generated using datetime.datetime.strptime, so if somebody
    #tries to inject SQL there, it will fail
    con.cursor().execute("SET SCHEMA '{}'".format(schema))

    #Print the current schema by reading it from the db
    cur = con.cursor()    
    cur.execute('SELECT current_schema;')
    current_schema = cur.fetchone()[0]
    logger.info(('Starting feature generation in {}. '
                 'n_months={}. max_dist={}').format(current_schema, n_months, max_dist))
    #Get existing tables
    existing_tables =  tables_in_schema(schema)
    
    # set the search path, otherwise won't find ST_DWithin()
    cur = con.cursor()
    cur.execute("SET search_path TO {schema}, public;".format(schema=schema))
    con.commit()

    # make a new table that contains one row for every parcel in Cincinnati
    # this table has three columns: parcel_id, inspection_date, viol_outcome
    # inspection_date is the one given as a parameter and
    # is the same for all parcels
    if 'parcels_inspections' not in existing_tables:
        logger.info('Creating parcels_inspections table...')

        if inspection_date is None:
            inspections = outcome.generate_labels()
        else:
          if insp_set=='all_inspections':
            inspections = outcome.make_fake_inspections_all_parcels_cincy(inspection_date)
          elif insp_set=='field_test':
            inspections = outcome.load_inspections_from_field_test(inspection_date)

        inspections.to_sql("parcels_inspections", engine, chunksize=50000,
                      if_exists='fail', index=False, schema=schema)
        logging.debug("... table has {} rows".format(len(inspections)))
        #Create an index to make joins with events_Xmonths_* tables faster
        cur.execute('CREATE INDEX ON parcels_inspections (parcel_id);')
        cur.execute('CREATE INDEX ON parcels_inspections (inspection_date);')
        cur.execute('CREATE INDEX ON parcels_inspections (parcel_id, inspection_date);')
        con.commit()
    else:
        logger.info('parcels_inspections table already exists, skipping...')

    for feature in features_to_generate:
        logging.info("Generating {} features".format(feature.table))
        #Try generating features with the n_months argument
        try:
            logging.info(("Generating {} "
                          "features for {} months "
                          "and within {} m").format(feature.table, n_months, max_dist))
            feature_data = feature.generator_function(con, n_months, max_dist)
            table_to_save = '{}_{}m_{}months'.format(feature.table, max_dist, n_months)
        #If it fails, feature is not spatiotemporal, send only connection
        except Exception, e:
            table_to_save = feature.table
            logging.info("Failed to call function with months and dist: {}".format(str(e)))
            feature_data = feature.generator_function(con)
        #Every generator function must have a column with parcel_id,
        #inspection_date and the correct number of rows as their
        #corresponding parcels_inspections table in the schema being used
        # TO DO: check that feature_data has the right shape and indexes
        if table_to_save in existing_tables:
            logger.info('Features table {} already exists. Replacing...'.format(feature.table))

        feature_data.to_sql(table_to_save, engine, chunksize=50000,
          if_exists='replace', index=True, schema=schema,
          #Force saving inspection_date as timestamp without timezone
          dtype={'inspection_date': types.TIMESTAMP(timezone=False)})
        logging.debug("{} table has {} rows".format(table_to_save, len(feature_data)))

if __name__ == '__main__':
    #Get the table names for existing features
    tables = [t.table for t in existing_features]
    #Create a list to show it to the user
    tables_list = reduce(lambda x,y: x+", "+y, tables)

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--date",
                        help=("To generate features for if an inspection happens "
                              "at certain date. e.g. 01Jul2015"), type=str)
    parser.add_argument("-f", "--features", type=str, default="all",
                            help=("Comma separated list of features to generate "
                                  "Possible values are %s. Defaults to all, which "
                                  "will generate all possible features" % tables_list))
    parser.add_argument("-m", "--months",
                        help=("Count events that happened m months "
                              "before inspection took place. "
                              "Only supported by spatiotemporal features. "
			                  "Defaults to 3 months"), type=int,
			                  default=3)
    parser.add_argument("-md", "--maxdist",
                        help=("Count events that happened max m meters "
                              "from inspection. "
                              "Only supported by spatiotemporal features. "
                              "Defaults to 1000 m (max value posible)"), type=int,
                        default=1000)
    parser.add_argument("-s", "--set", type=str,
                        choices=['all_inspections', 'field_test'],
                        help=("Which inspections set to use, "
                          "all_inspections will use shape_files.parcels_cincy table, "
                          "field_test will use public.field_test table. Defaults "
                          "to all_inspections"),
                        default='all_inspections')
    args = parser.parse_args()

    #Based on user selection create an array with the features to generate
    #Based on user selection, select method to use
    if args.features == 'all':
        selected_features = existing_features
    else:
        selected_tables = args.features.split(",")
        selected_features = filter(lambda x: x.table in selected_tables, existing_features)
    
    if len(selected_features)==0:
        raise NoFeaturesSelected('You did not select any features')
   
    selected  = [t.table for t in selected_features]
    selected = reduce(lambda x,y: x+", "+y, selected) 
    print "Selected features: %s" % selected
    d = datetime.datetime.strptime(args.date, '%d%b%Y') if args.date not in [None, "None"] else None

    generate_features(selected_features, args.months, args.maxdist, d, args.set)
