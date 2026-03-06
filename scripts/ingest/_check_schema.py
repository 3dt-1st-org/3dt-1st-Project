import sys; sys.path.insert(0, r'c:\Users\EL035\dataschool\08_First_Team_Project\3dt-1st-Project')
import psycopg2
DSN = 'host=lala-db.postgres.database.azure.com port=5432 dbname=postgres user=admin_user password=Aremarem2 sslmode=require'
conn = psycopg2.connect(DSN)
cur = conn.cursor()

cur.execute("""
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'locallink' AND table_name = 'tourist_spot_info'
ORDER BY ordinal_position
""")
print('=== tourist_spot_info 컬럼 ===')
for r in cur.fetchall():
    print(f'  {r[0]:35s} {r[1]}')

cur.execute("""
SELECT tourist_nm, sigun_nm, cat1, cat2, cat3, overview
FROM locallink.tourist_spot_info
WHERE tourist_nm ILIKE '%수원화성%' OR tourist_nm ILIKE '%연무대%'
LIMIT 5
""")
print('\n=== 수원화성/연무대 카테고리 샘플 ===')
cols = [d[0] for d in cur.description]
for row in cur.fetchall():
    for c, v in zip(cols, row):
        if v:
            print(f'  {c}: {str(v)[:120]}')
    print()

# cat1/cat2/cat3 전체 분포
for col in ['cat1', 'cat2', 'cat3']:
    cur.execute(f"SELECT {col}, count(*) FROM locallink.tourist_spot_info GROUP BY 1 ORDER BY 2 DESC LIMIT 15")
    rows = cur.fetchall()
    if rows and rows[0][0] is not None:
        print(f'\n=== {col} 분포 (상위 15개) ===')
        for r in rows:
            print(f'  {str(r[0]):40s} {r[1]}')

conn.close()
