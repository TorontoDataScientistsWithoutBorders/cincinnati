PATH_TO_MODEL="$ROOT_FOLDER/blight_risk_prediction"
PATH_TO_EXP="$ROOT_FOLDER/experiments/kdd"
CORES=4

$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_1years.yaml
$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_2years.yaml
$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_3years.yaml
$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_4years.yaml
$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_5years.yaml
$PATH_TO_MODEL/model.py -n $CORES -c $PATH_TO_EXP/freq_features_6years.yaml
