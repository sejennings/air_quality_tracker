"""Evaluate decisions against an independent observed-concentration rule."""


def evaluate(frame, pm25_limit, ozone_limit, reconstructed=False):
    result = frame.copy()
    observed = (result.pm25 >= pm25_limit) | (result.ozone_8hr_max >= ozone_limit)
    decision = ((result.pm25_reconstructed >= pm25_limit) | (result.ozone_reconstructed >= ozone_limit)) if reconstructed else result.anomaly.astype(bool)
    result['Observed exceedance'] = observed
    result['Compared decision'] = decision
    result['Outcome'] = ['Correctly flagged' if actual and predicted else 'Missed day' if actual else 'False alarm' if predicted else 'Correctly unflagged' for actual, predicted in zip(observed, decision)]
    tp = int((observed & decision).sum())
    fn = int((observed & ~decision).sum())
    fp = int((~observed & decision).sum())
    tn = int((~observed & ~decision).sum())
    return result, {'Correctly flagged': tp, 'Missed days': fn, 'False alarms': fp, 'Correctly unflagged': tn, 'Observed exceedance days': tp + fn, 'Accuracy': (tp + tn) / len(result) if len(result) else None, 'Precision': tp / (tp + fp) if tp + fp else None, 'Recall': tp / (tp + fn) if tp + fn else None}
