from datetime import datetime, timezone
from network_distribution.geo import GeoRecord
from network_distribution.persistence import save_geo_cache, select_sources

class Cursor:
 def __init__(self, rows=()): self.rows=rows; self.calls=[]
 def __enter__(self): return self
 def __exit__(self,*a): pass
 def execute(self,sql,args=None): self.calls.append((sql,args))
 def fetchall(self): return self.rows
class Connection:
 def __init__(self,rows=()): self.cursor_value=Cursor(rows); self.commits=0
 def cursor(self): return self.cursor_value
 def commit(self): self.commits+=1

def test_source_selection_exact_policy():
 connection=Connection([(2,'https://selected'),(1,'https://other')]); rows=select_sources(connection,'chain',3,600)
 sql,args=connection.cursor_value.calls[0]
 assert rows[0]['id']==2 and args==('chain',600,3)
 for fragment in ['chain_id = %s','is_enabled AND healthy','catching_up IS FALSE','last_checked_at IS NOT NULL','is_selected DESC','latest_observed_height DESC NULLS LAST','id ASC','LIMIT %s']: assert fragment in sql

def test_geo_upsert_is_explicit_and_downgrade_protected():
 now=datetime.now(timezone.utc); connection=Connection(); row=GeoRecord('8.8.8.8',False,error_code='timeout',fetched_at=now,expires_at=now)
 save_geo_cache(connection,[row]); sql,args=connection.cursor_value.calls[0]
 assert args==(row.ip,row.lookup_success,row.continent_name,row.country_code,row.country_name,row.region_name,row.asn,row.provider_name,row.lookup_provider,row.fetched_at,row.expires_at,row.error_code)
 assert 'network_distribution_geo_cache.expires_at <= now()' in sql
 assert 'OR NOT network_distribution_geo_cache.lookup_success' in sql
