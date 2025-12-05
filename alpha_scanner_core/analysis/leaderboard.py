import pandas as pd

def create_leaderboard(results_list):
    """
    Takes a list of result dictionaries and returns a sorted DataFrame.
    """
    if not results_list:
        return pd.DataFrame()

    df = pd.DataFrame(results_list)

    # Ensure robustness_score exists
    if 'robustness_score' not in df.columns:
        return df

    # Sort by Robustness Score descending
    df = df.sort_values(by='robustness_score', ascending=False).reset_index(drop=True)

    # Rank
    df.index = df.index + 1
    df.index.name = 'Rank'

    return df
