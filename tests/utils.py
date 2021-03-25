import numpy as np


def assert_dfs(df_a, df_b, eps=1e-10):
    assert df_a.index.equals(df_b.index)
    assert np.array_equal(df_a.columns, df_b.columns)

    cols = sorted(df_a.columns)
    assert ((df_a[cols].values - df_b[cols].values) < eps).all()
