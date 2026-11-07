CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE,                       -- Duke address receipts are sent to / forwarded from
  is_demo BOOLEAN NOT NULL DEFAULT FALSE,
  settings JSONB NOT NULL DEFAULT '{}'     -- Settings model (section 9)
);

-- NetNutrition catalog
CREATE TABLE IF NOT EXISTS nn_units (
  unit_oid INT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'retail'      -- 'retail' | 'dining_hall'
);
CREATE TABLE IF NOT EXISTS nn_items (
  item_oid BIGINT PRIMARY KEY,
  unit_oid INT NOT NULL REFERENCES nn_units(unit_oid),
  course TEXT,                             -- "Choose Protein"
  name TEXT NOT NULL,
  allergens TEXT[] NOT NULL DEFAULT '{}',  -- egg fish gluten milk peanut sesame shellfish soy tree_nut wheat
  diets TEXT[] NOT NULL DEFAULT '{}',      -- halal vegan vegetarian
  ingredients TEXT,
  menu_date DATE,                          -- dining halls only
  meal TEXT,                               -- dining halls only: Breakfast/Brunch/Lunch/Dinner
  scraped_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS nn_portions (
  item_oid BIGINT NOT NULL REFERENCES nn_items(item_oid) ON DELETE CASCADE,
  uofm_oid BIGINT NOT NULL,
  portion_name TEXT NOT NULL,              -- "Burrito Portion"
  is_default BOOLEAN NOT NULL,
  grams REAL,
  calories REAL, protein_g REAL, carbs_g REAL, fat_g REAL,
  fiber_g REAL, sugar_g REAL, sodium_mg REAL,
  PRIMARY KEY (item_oid, uofm_oid)
);

-- Our vendors (receipt names) mapped to NetNutrition units
CREATE TABLE IF NOT EXISTS vendors (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,               -- canonical, e.g. "Sazon"
  building TEXT,
  unit_oid INT REFERENCES nn_units(unit_oid),  -- NULL = no nutrition data (Gothic Grill)
  hours JSONB NOT NULL DEFAULT '{}'        -- {"mon":[["11:00","20:00"]]} local; hand-seeded
);
CREATE TABLE IF NOT EXISTS vendor_aliases (raw TEXT PRIMARY KEY, vendor_id INT NOT NULL REFERENCES vendors(id));
CREATE TABLE IF NOT EXISTS item_aliases (
  vendor_id INT NOT NULL REFERENCES vendors(id),
  raw TEXT NOT NULL,                       -- lowercased receipt name
  item_oid BIGINT NOT NULL REFERENCES nn_items(item_oid),
  PRIMARY KEY (vendor_id, raw)
);

-- What things cost (from receipts and manual entry)
CREATE TABLE IF NOT EXISTS prices (
  vendor_id INT NOT NULL REFERENCES vendors(id),
  item_name TEXT NOT NULL,                 -- receipt item name, e.g. "Burrito"
  variant TEXT NOT NULL DEFAULT '',        -- priced component if any, e.g. "Hot Honey Chicken"
  price NUMERIC(6,2) NOT NULL,
  source TEXT NOT NULL,                    -- 'receipt' | 'manual'
  observed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (vendor_id, item_name, variant)   -- keep latest
);

-- What the user ate and paid
CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  ts TIMESTAMPTZ NOT NULL,
  vendor_id INT REFERENCES vendors(id),
  vendor_raw TEXT NOT NULL,
  subtotal NUMERIC(6,2), tax NUMERIC(6,2), total NUMERIC(6,2),
  points_spent NUMERIC(6,2) NOT NULL,      -- "Student Food" tender
  swipes_used INT NOT NULL DEFAULT 0,
  swipe_value NUMERIC(6,2) NOT NULL DEFAULT 0,
  source TEXT NOT NULL,                    -- 'email' | 'manual' | 'seed'
  external_ref TEXT,                       -- Transact order number
  raw_email BYTEA,
  macros_partial BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (user_id, external_ref)
);
CREATE TABLE IF NOT EXISTS order_items (
  id SERIAL PRIMARY KEY,
  order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  price NUMERIC(6,2),
  format TEXT                              -- 'burrito' | 'quesadilla' | 'arepa_bowl' | 'taco' | NULL
);
CREATE TABLE IF NOT EXISTS order_components (  -- what macros are computed from
  order_item_id INT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
  raw_name TEXT NOT NULL,
  item_oid BIGINT REFERENCES nn_items(item_oid),   -- NULL = unmatched
  uofm_oid BIGINT,
  servings REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
  user_id INT NOT NULL REFERENCES users(id),
  ts TIMESTAMPTZ NOT NULL,
  points NUMERIC(8,2) NOT NULL,
  swipes INT,
  PRIMARY KEY (user_id, ts)
);
CREATE TABLE IF NOT EXISTS coach_cache (
  kind TEXT NOT NULL, input_hash TEXT NOT NULL, output JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, input_hash)
);
