from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "code-review" / "scripts"
sys.path.insert(0, str(SCRIPTS))

PATCH = """@@ -1,2 +1,6 @@
 def add(a, b):
     return a + b
+
+
+def div(a, b):
+    return a / b
@@ -20,3 +24,4 @@ class Store:
     def save(self, rows):
         for row in rows:
-            self.db.insert(row)
+            self.db.insert(row)
+            self.count += 1
"""
