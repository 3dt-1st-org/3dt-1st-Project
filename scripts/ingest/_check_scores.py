import sys, re
sys.path.insert(0, r'c:\Users\EL035\dataschool\08_First_Team_Project\3dt-1st-Project')
from config.vault_manager import get_vault_manager
from openai import AzureOpenAI
import psycopg2

vm = get_vault_manager()
raw_ep = vm.get_secret('azure-openai-endpoint').rstrip('/')
client = AzureOpenAI(
    api_key=vm.get_secret('azure-openai-key'),
    azure_endpoint=raw_ep,
    api_version=vm.get_secret('azure-openai-embedding-api-version') or '2024-02-01',
)
dep = vm.get_secret('azure-openai-embedding-deployment-name')
resp = client.embeddings.create(model=dep, input='조용하고 역사적인 실내 전시관')
vec_str = '[' + ','.join(map(str, resp.data[0].embedding)) + ']'
print(f'임베딩 생성 OK: {len(resp.data[0].embedding)} 차원')

DSN = 'host=lala-db.postgres.database.azure.com port=5432 dbname=postgres user=admin_user password=Aremarem2 sslmode=require'
conn = psycopg2.connect(DSN)
cur = conn.cursor()
cur.execute('''
SELECT 
    attraction_name,
    ROUND((MIN(embedding <=> %s::vector))::numeric, 4)  AS cosine_dist,
    ROUND((1 - MIN(embedding <=> %s::vector)/2)::numeric, 4) AS similarity
FROM locallink.attraction_reviews
WHERE embedding IS NOT NULL
GROUP BY attraction_name
''', (vec_str, vec_str))

print('\n=== 실제 벡터 유사도 ===')
print(f"  {'명칭':<20} {'코사인거리':>10} {'유사도(sim)':>12} {'최종스코어(dist=1m)':>20}")
for row in cur.fetchall():
    name, cd, sim = row
    final = float(cd)/2 * 0.7 + (1/10000) * 0.3
    print(f"  {str(name):<20} {float(cd):>10.4f} {float(sim):>12.4f} {final:>20.6f}")

print(f"  {'수원호스텔식당(19m)':<20} {'N/A':>10} {'N/A':>12} {19/10000:>20.6f}")
print(f"\n  ※ 스코어가 낮을수록 순위 높음 (ASC 정렬)")
print(f"  → 관광지 스코어 > 0.001 이면 19m 음식점에 밀림")
conn.close()
