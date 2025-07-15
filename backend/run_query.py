import sqlite3
from datetime import datetime
import pytz

# Lokasi database
db_path = 'instance/glucotracker.db'  # sesuaikan jika lokasi berbeda

# Query yang ingin dijalankan
query = '''
SELECT input_value, sugar_result, timestamp
FROM glucose_log
ORDER BY timestamp DESC;
'''

# Koneksi ke database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Eksekusi query
cursor.execute(query)
results = cursor.fetchall()

# Konversi timezone UTC → Asia/Jakarta
jakarta_tz = pytz.timezone('Asia/Jakarta')

print("Input\t\t|\tSugar (g)\t|\tTimestamp (WIB)")
print("-" * 70)
for row in results:
    input_val, sugar, timestamp = row
    utc_dt = datetime.fromisoformat(timestamp).replace(tzinfo=pytz.utc)
    wib_dt = utc_dt.astimezone(jakarta_tz)
    print(f"{input_val[:15]:<15} | {sugar:<12.2f} | {wib_dt.strftime('%Y-%m-%d %H:%M:%S')}")

# Tutup koneksi
cursor.close()
conn.close()
