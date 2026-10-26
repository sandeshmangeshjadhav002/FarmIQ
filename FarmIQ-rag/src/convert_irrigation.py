"""Convert the irrigation Excel file to clean CSV."""
import pandas as pd

df = pd.read_excel(
    'datasets/raw/irrigation/Project_datasheet_2019-2020.xlsx',
    sheet_name='Project datasheet',
)
cols = ['CropType', 'CropDays', 'Soil Moisture', 'Soil Temperature',
        'Temperature', 'Humidity', 'Irrigation(Y/N)']
df = df[cols].dropna().copy()
df.columns = ['CropType', 'CropDays', 'SoilMoisture', 'SoilTemperature',
              'Temperature', 'Humidity', 'Irrigation']
df.to_csv('datasets/raw/irrigation/irrigation_dataset.csv', index=False)
print(f'Saved {len(df)} rows to irrigation_dataset.csv')
print(df.head(5).to_string())
print(f'\nIrrigation value counts: {dict(df["Irrigation"].value_counts())}')
