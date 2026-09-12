CREATE TABLE IF NOT EXISTS users (
  id INT64,
  first_name STRING,
  last_name STRING,
  email STRING,
  age INT64,
  gender STRING,
  state STRING,
  street_address STRING,
  postal_code STRING,
  city STRING,
  country STRING,
  latitude FLOAT64,
  longitude FLOAT64,
  traffic_source STRING,
  created_at TIMESTAMP,
  user_geom GEOGRAPHY
);

CREATE TABLE IF NOT EXISTS products (
  id INT64,
  cost FLOAT64,
  category STRING,
  name STRING,
  brand STRING,
  retail_price FLOAT64,
  department STRING,
  sku STRING,
  distribution_center_id INT64
);

CREATE TABLE IF NOT EXISTS orders (
  order_id INT64,
  user_id INT64,
  status STRING,
  gender STRING,
  created_at TIMESTAMP,
  returned_at TIMESTAMP,
  shipped_at TIMESTAMP,
  delivered_at TIMESTAMP,
  num_of_item INT64
);

CREATE TABLE IF NOT EXISTS order_items (
  id INT64,
  order_id INT64,
  user_id INT64,
  product_id INT64,
  inventory_item_id INT64,
  status STRING,
  created_at TIMESTAMP,
  shipped_at TIMESTAMP,
  delivered_at TIMESTAMP,
  returned_at TIMESTAMP,
  sale_price FLOAT64
);
