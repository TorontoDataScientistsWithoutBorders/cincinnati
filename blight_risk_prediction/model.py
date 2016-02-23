#!/usr/bin/env python
import pandas as pd
import datetime
import yaml
import pickle
import sys
import os
import logging
import logging.config
import copy
from itertools import product
import numpy as np
from sklearn import linear_model, svm, ensemble
import dataset, evaluation, util
from features import feature_parser
import argparse
from sklearn import preprocessing
from sklearn.externals import joblib

from dstools.config import main as cfg_main
from dstools.config import load
from sklearn_evaluation.Logger import Logger
from sklearn_evaluation.metrics import precision_at
from grid_generator import grid_from_class

"""
Purpose: train a binary classifier to identify those homes that are likely
to have at least one violation.
"""

logging.config.dictConfig(load('logger_config.yaml'))
logger = logging.getLogger()

#Where to save test set predictions
path_to_predictions = os.path.join(os.environ['OUTPUT_FOLDER'], "predictions")
#Where to pickle models
path_to_pickles = os.path.join(os.environ['OUTPUT_FOLDER'], "pickles")
#Make directories if they don't exist

for directory in [path_to_pickles, path_to_predictions]:
    if not os.path.exists(directory):
        os.makedirs(directory)

field_test_dir = "field_test_predictions/"

class ConfigError():
    pass

def configure_model(config_file):
    logger.info("Reading config from {}".format(config_file))
    with open(config_file, 'r') as f:
        cfg = yaml.load(f)

    if "start_date" not in cfg:
        cfg["start_date"] = '01Jan1970'

    if "residential_only" not in cfg:
        cfg["residential_only"] = False

    # predict parcels
    if "prepare_field_test" in cfg:
        if "prepare_field_test" not in cfg:
            errmsg = "Set an inspection date to generate parcels to inspect"
            raise ConfigError(errmsg)
    else:
        cfg["prepare_field_test"] = False

    return cfg, copy.deepcopy(cfg)

def make_datasets(config):

    start_date = datetime.datetime.strptime(config["start_date"], '%d%b%Y')
    fake_today = datetime.datetime.strptime(config['fake_today'], '%d%b%Y')

    if config["validation_window"] == "1Year":
        validation_window = datetime.timedelta(days=365)
    elif config["validation_window"] == "1Month":
        validation_window = datetime.timedelta(days=30)
    else:
        raise ConfigError("Unsupported validation window: {}".format(
                          config["validation_window"]))

    #Parse each feature pattern (table_name.pattern) in the config file and
    #return a list with tuples of the form (table_name, feature_name)
    features = feature_parser.parse_feature_pattern_list(config["features"])
    #print 'Selected features based on yaml file %s' % features

    only_residential = config["residential_only"]

    #Train set is built with a list of features, parsed from the configuration
    #file. Data is obtained between start date and fake today.
    #it is possible to select residential parels only.
    #Data is obtained from features schema
    train = dataset.get_training_dataset(
        features=features,
        start_date=start_date,
        end_date=fake_today,
        only_residential=only_residential)

    #Test set is built in a similar way: list of features parsed from configuration
    #file, but the start date is just where out trainin set finishes and the end date
    #is the validation window. Residential flag also applies
    #Data is obtained from features schema
    test = dataset.get_testing_dataset(
        features=features,
        start_date=fake_today,
        end_date=fake_today + validation_window,
        only_residential=only_residential)

    field_train, field_test = None, None

    if config["prepare_field_test"]:
        inspection_date = datetime.datetime.strptime(config["inspection_date"],
                                                     '%d%b%Y')
        #To make predictions for field testing we need to create a training datasets
        #similar to the ones used for the experiments, the start date is the same
        #as sppecified in the configuration file but the end date must be the inspection
        #date.
        #Data is obtained from features schema
        field_train = dataset.get_training_dataset(
            features=features,
            start_date=start_date,
            end_date=inspection_date,
            only_residential=only_residential)
        #The test set is going to be used to predict in each parcel and then output
        #results to a file that will be send to our partner. The dataset created using
        #this function will use all parcels in cincinnati, but it will fake the inspection
        #date for the desired date, and features will be generated according to such date
        #Data is obtained from features_DATE schema, where DATE is the desired
        #date of inspection
        field_test = dataset.get_field_testing_dataset(
            features=features,
            fake_inspection_date=inspection_date,
            only_residential=only_residential)

    return train, test, field_train, field_test

def output_evaluation_statistics(test, predictions):
    logger.info("Statistics with probability cutoff at 0.5")
    # binary predictions with some cutoff for these evaluations
    cutoff = 0.5
    predictions_binary = np.copy(predictions)
    predictions_binary[predictions_binary >= cutoff] = 1
    predictions_binary[predictions_binary < cutoff] = 0

    evaluation.print_model_statistics(test.y, predictions_binary)
    evaluation.print_confusion_matrix(test.y, predictions_binary)

    precision1 = precision_at(test.y, predictions, 0.01)
    logger.debug("Precision at 1%: {} (probability cutoff {})".format(
                 round(precision1[0], 2), precision1[1]))
    precision10 = precision_at(test.y, predictions, 0.1)
    logger.debug("Precision at 10%: {} (probability cutoff {})".format(
                 round(precision10[0], 2), precision10[1]))
    #evaluation.plot_precision_at_varying_percent(test.y, predictions)

def get_feature_importances(model):
    try:
        return model.feature_importances_
    except:
        pass
    try:
        logging.info(('This model does not have feature_importances, '
                      'returning .coef_[0] instead.'))
        return model.coef_[0]
    except:
        logging.info(('This model does not have feature_importances, '
                      'nor coef_ returning None'))
    return None

def log_results(model, config, test, predictions, feature_importances):
    '''
        Log results to a MongoDB database
    '''
    #Instantiate logger
    logger_uri = cfg_main['logger']['uri']
    logger_db = cfg_main['logger']['db']
    logger_collection = cfg_main['logger']['collection']
    mongo_logger = Logger(logger_uri, logger_db, logger_collection)
    #Compute some statistics to log
    prec_at_1, cutoff_at_1 = precision_at(test.y, predictions, 0.01)
    prec_at_10, cutoff_at_10 = precision_at(test.y, predictions, 0.1)
    #Add the name of the experiment if available
    experiment_name = config["experiment_name"] if config["experiment_name"] else None
    #Sending model will log model name, parameters and datetime
    #Also log other important things by sending named parameters
    mongo_id = mongo_logger.log_model(model, features=list(test.feature_names),
        feature_importances=list(feature_importances),
        config=config, prec_at_1=prec_at_1,
        prec_at_10=prec_at_10, cutoff_at_1=cutoff_at_1,
        cutoff_at_10=cutoff_at_10, experiment_name=experiment_name)

    #Dump test_labels, test_predictions and test_parcels to a csv file
    parcel_id = [record[0] for record in test.parcels]
    inspection_date = [record[1] for record in test.parcels]
    dump = pd.DataFrame({'parcel_id': parcel_id,
        'inspection_date': inspection_date,
        'viol_outcome': test.y,
        'prediction': predictions})
    #Dump predictions to CSV
    dump.to_csv(os.path.join(path_to_predictions, mongo_id))
    #Pickle model
    joblib.dump(model, os.path.join(path_to_pickles, mongo_id)) 

def main():
    config_file = args.path_to_config_file
    config, config_raw = configure_model(config_file)

    # datasets
    train, test, field_train, field_test = make_datasets(config)
    # Dump datasets if dump option was selected
    if args.dump:
        logger.info('Dumping train, test, field_train and field_test')
        #Make the directory if does not exists to prevent errors
        path = os.path.join(os.environ['OUTPUT_FOLDER'], "dumps")
        if not os.path.exists(path):
            os.makedirs(path)
        datasets = [(train, 'train'), 
                    (test, 'test'),
                    (field_train, 'field_train'),
                    (field_test, 'field_test')]
        for data, name in datasets:
            if data is not None:
                filename = '{}_{}.csv'.format(config["experiment_name"], name)
                df = data.to_df()
                df.to_csv(os.path.join(path, filename))
            else:
                logger.info('{} is None, skipping dump...'.format(name))


    #Impute missing values (mean is the only strategy for now)
    logger.info('Imputing values on train and test...')
    train.impute()
    test.impute()

    # Scale features to zero mean and unit variance
    logger.info('Scaling train, test...')
    scaler = preprocessing.StandardScaler().fit(train.x)
    train.x = scaler.transform(train.x)
    test.x = scaler.transform(test.x)

    #Get size of grids
    grid_size = config["grid_size"]
    #Get list of models selected
    models_selected = config["models"]
    #Get grid for each class
    grids = [grid_from_class(m, size=grid_size) for m in models_selected]
    #Flatten list
    models = [a_grid for a_model_grid in grids for a_grid in a_model_grid]

    # fit each model for all of these
    for idx, model in enumerate(models):
        #Try to run in parallel if possible
        if hasattr(model, 'n_jobs'):
            model.set_params(n_jobs=args.n_jobs)

        #SVC does not predict probabilities by default
        if hasattr(model, 'probability'):
            model.probability = True

        timestamp = datetime.datetime.now().isoformat()

        # train
        logger.info("{} out of {} - Training {}".format(model,
                                                        idx+1,
                                                        len(models)))
        model.fit(train.x, train.y)

        # predict
        logger.info("Predicting on validation samples...")
        predicted = model.predict_proba(test.x)
        predicted = predicted[:, 1]  # probability that label is 1

        # statistics
        output_evaluation_statistics(test, predicted)
        feature_importances = get_feature_importances(model)

        # save results
        prefix = config["experiment_name"] if config["experiment_name"] else ''
        outfile = "{prefix}{timestamp}.pkl".format(prefix=prefix,
                                                   timestamp=timestamp)
        config_raw["parameters"] = model.get_params()
        
        #Log depending on user selection
        if args.notlog:
            logger.info("You selected not to log results. Skipping...")
        else:
            #Log parameters and metrics to MongoDB
            #Save predictions to CSV file
            #and pickle model
            log_results(model, config_raw, test, predicted,
                feature_importances)

        # generate blight probabilities for field test
        if config["prepare_field_test"]:
            #Impute missing values (mean is the only strategy for now)
            logger.info('Imputing values on field_train and field_test...')
            field_train.impute()
            field_test.impute()
            
            # Scale features to zero mean and unit variance
            logger.info('Scaling field_train, field_test...')
            scaler = preprocessing.StandardScaler().fit(field_train.x)
            field_train.x = scaler.transform(field_train.x)
            field_test.x = scaler.transform(field_test.x)

            logger.info("Predicting for all cincinnati parcels ")
            model.fit(field_train.x, field_train.y)

            fake_inspections_probs = model.predict_proba(field_test.x)
            # probability that label is 1
            fake_inspections_probs = fake_inspections_probs[:, 1]

            # make a csv with the predictions
            index = pd.MultiIndex.from_tuples(
                field_test.parcels, names=['parcel', 'inspection_date'])
            parcels_with_probabilities = pd.Series(
                fake_inspections_probs, index=index)
            parcels_with_probabilities.sort(ascending=False)
            outfile = os.path.join(field_test_dir,
                                   "{}.csv".format(timestamp))
            parcels_with_probabilities.to_csv(outfile)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--path_to_config_file",
                        help=("Path to the yaml configuration file. "
                              "Defaults to the default.yaml in the $ROOT_FOLDER"),
                        type=str, default=os.path.join(os.environ["ROOT_FOLDER"], "default.yaml"))
    #Two options for saving results: 1. save to mongodb, you
    #can use something like MongoChef to see results (to do that you need to
    #provided a mongo URI in the config.yaml file). 2. Pickle results (you can see
    #results with the webapp)
    #Important: even if you use MONGO, for performance reasons, some results will
    #still be saved as csv files in your $OUTPUT_FOLDER
    parser.add_argument("-n", "--n_jobs", type=int, default=-1,
                            help=("n_jobs flag passed to scikit-learn models, "
                                  "fails silently if the model does not support "
                                  "such flag. Defaults to -1 (all jobs possible)"))
    parser.add_argument("-nl", "--notlog", action="store_true",
                        help="Do not log results to MongoDB and pickle model")
    parser.add_argument("-d", "--dump", action="store_true",
                        help=("Dump train and test sets (including indexes), "
                              "before imputation and scaling. "
                              "Output will be saved as "
                              "$OUTPUT_FOLDER/dumps/[experiment_name]_[train/test]"))
    args = parser.parse_args()
    main()
