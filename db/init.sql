-- 카테고리 예: 'umbrella', 'charger_c'
CREATE TABLE IF NOT EXISTS inventory (
  id SERIAL PRIMARY KEY,
  category VARCHAR(50) NOT NULL,
  name VARCHAR(100) NOT NULL UNIQUE,
  holder VARCHAR(200) NULL -- 현재 대여자(없으면 NULL)
);

-- 우산 2개
INSERT INTO inventory (category, name, holder) VALUES
('umbrella', '우산#1', NULL),
('umbrella', '우산#2', NULL)
ON CONFLICT DO NOTHING;

-- C타입 충전기 3개
-- INSERT INTO inventory (category, name, holder) VALUES
-- ('charger_c', 'C타입충전기#1', NULL),
-- ('charger_c', 'C타입충전기#2', NULL),
-- ('charger_c', 'C타입충전기#3', NULL)
-- ON CONFLICT DO NOTHING;
