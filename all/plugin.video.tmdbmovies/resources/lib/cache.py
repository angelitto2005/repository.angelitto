import json
import time
from resources.lib.database import connect

class MainCache:
    def __init__(self):
        self.dbcon = connect()
        self.dbcur = self.dbcon.cursor()

    def get(self, string):
        """Obține date din cache dacă sunt valide."""
        try:
            current_time = int(time.time())
            self.dbcur.execute("SELECT expires, data FROM maincache WHERE id = ?", (string,))
            result = self.dbcur.fetchone()
            
            if result:
                expires, data = result
                if expires > current_time:
                    return json.loads(data)
                else:
                    self.delete(string)
        except:
            pass
        return None

    def set(self, string, data, expiration=48):
        """Salvează date în cache. Expiration este în ore."""
        try:
            expires = int(time.time() + (expiration * 3600))
            self.dbcur.execute("INSERT OR REPLACE INTO maincache (id, data, expires) VALUES (?, ?, ?)", 
                               (string, json.dumps(data), expires))
            self.dbcon.commit()
        except:
            pass

    def delete(self, string):
        """Șterge o intrare specifică."""
        try:
            self.dbcur.execute("DELETE FROM maincache WHERE id = ?", (string,))
            self.dbcon.commit()
        except:
            pass
            
    def delete_all(self):
        """Șterge tot cache-ul."""
        try:
            self.dbcur.execute("DELETE FROM maincache")
            self.dbcon.execute("VACUUM")
            self.dbcon.commit()
        except:
            pass

def cache_object(function, string, url, json_output=True, expiration=48):
    """
    Decorator/Wrapper inteligent pentru funcții.
    Verifică cache-ul înainte de a apela API-ul.
    """
    cache = MainCache()
    cached_data = cache.get(string)
    
    if cached_data:
        return cached_data
    
    # Dacă nu e în cache, executăm funcția
    if isinstance(url, list):
        result = function(*url)
    else:
        result = function(url)
        
    if result:
        if json_output and hasattr(result, 'json'):
            try:
                data = result.json()
            except:
                data = result
        else:
            data = result
            
        cache.set(string, data, expiration=expiration)
        return data
        
    return None