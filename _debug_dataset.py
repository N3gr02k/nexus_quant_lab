import pandas as pd
import numpy as np

df = pd.read_csv('data/alpha_master_dataset.csv', index_col='time', parse_dates=True)
print('Shape:', df.shape)
print()

alpha_cols = [c for c in df.columns if 'alpha' in c]
print('Alpha cols:', alpha_cols)
print()

for col in alpha_cols:
    nan_count = df[col].isna().sum()
    ok_count = df[col].notna().sum()
    print(f'{col}: NaN={nan_count}, OK={ok_count}')

print()
print('Target distribution:')
print(df['target'].value_counts())
print(f'Target mean: {df["target"].mean():.4f}')

# Check first few rows of alpha columns
print('\nFirst 5 rows of alpha columns:')
print(df[alpha_cols].head(10))
