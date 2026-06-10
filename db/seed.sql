-- =============================================================================
-- Ontology-Driven Agentic Staffing System
-- Seed Data — Phase 1
-- =============================================================================

-- Use explicit UUIDs so FK references are deterministic
-- All dates relative to a baseline of 2026-06-05

-- =============================================================================
-- PERSONS  (12 consultants across bands / regions)
-- =============================================================================
INSERT INTO person (id, name, email, role, band, location, office, region, hire_date, status, total_experience_months, experience_in_role_months) VALUES
-- EMEA
('a1000000-0000-0000-0000-000000000001', 'Amelia Hartley',      'amelia.hartley@enterprise.org',    'Partner',            'Partner',            'London',     'London HQ',       'EMEA',     '2006-03-01', 'active',  240, 60),
('a1000000-0000-0000-0000-000000000002', 'Thomas Becker',       'thomas.becker@enterprise.org',     'Senior Manager',     'Senior Manager',     'Frankfurt',  'Frankfurt Office','EMEA',     '2011-09-15', 'active',  180, 36),
('a1000000-0000-0000-0000-000000000003', 'Priya Sharma',        'priya.sharma@enterprise.org',      'Manager',            'Manager',            'London',     'London HQ',       'EMEA',     '2016-06-01', 'active',  120, 24),
('a1000000-0000-0000-0000-000000000004', 'Luca Rossi',          'luca.rossi@enterprise.org',        'Senior Consultant',  'Senior Consultant',  'London',     'London HQ',       'EMEA',     '2019-09-02', 'active',  84,  18),
('a1000000-0000-0000-0000-000000000005', 'Sophie Müller',       'sophie.muller@enterprise.org',     'Consultant',         'Consultant',         'Frankfurt',  'Frankfurt Office','EMEA',     '2023-01-16', 'bench',   36,  12),
-- Americas
('a1000000-0000-0000-0000-000000000006', 'James Whitfield',     'james.whitfield@enterprise.org',   'Director',           'Director',           'New York',   'New York Office', 'Americas', '2009-07-06', 'active',  200, 48),
('a1000000-0000-0000-0000-000000000007', 'Maria Gonzalez',      'maria.gonzalez@enterprise.org',    'Senior Consultant',  'Senior Consultant',  'New York',   'New York Office', 'Americas', '2018-08-20', 'active',  90,  30),
('a1000000-0000-0000-0000-000000000008', 'Derek Chen',          'derek.chen@enterprise.org',        'Analyst',            'Analyst',            'New York',   'New York Office', 'Americas', '2024-07-15', 'bench',   18,  18),
-- APAC
('a1000000-0000-0000-0000-000000000009', 'Kavya Nair',          'kavya.nair@enterprise.org',        'Manager',            'Manager',            'Singapore',  'Singapore Office','APAC',     '2017-03-13', 'active',  108, 20),
('a1000000-0000-0000-0000-000000000010', 'Rajan Mehta',         'rajan.mehta@enterprise.org',       'Senior Consultant',  'Senior Consultant',  'Mumbai',     'Mumbai Office',   'APAC',     '2020-05-04', 'active',  72,  24),
('a1000000-0000-0000-0000-000000000011', 'Olivia Thompson',     'olivia.thompson@enterprise.org',   'Consultant',         'Consultant',         'Sydney',     'Sydney Office',   'APAC',     '2022-02-28', 'active',  48,  14),
('a1000000-0000-0000-0000-000000000012', 'Wei Zhang',           'wei.zhang@enterprise.org',         'Analyst',            'Analyst',            'Singapore',  'Singapore Office','APAC',     '2025-08-11', 'bench',   12,  12);

-- =============================================================================
-- SKILLS
-- =============================================================================
INSERT INTO skills (id, person_id, skill_id, skill_name, skill_type, proficiency_level, years_experience) VALUES
-- Amelia Hartley — Partner, FinServ, Leadership
('b1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001', 'StrategyConsulting',     'Strategy Consulting',    'functional',   'expert',       18.0),
('b1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000001', 'ClientRelationships',    'Client Relationships',   'leadership',   'expert',       15.0),
('b1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000001', 'FinancialServices',      'Financial Services',     'domain',       'expert',       20.0),
('b1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000001', 'ExecutivePresence',      'Executive Presence',     'leadership',   'expert',       15.0),
-- Thomas Becker — Senior Manager, Data Engineering + Finance
('b1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000002', 'Python',                 'Python',                 'technical',    'expert',       10.0),
('b1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000002', 'Spark',                  'Apache Spark',           'technical',    'advanced',     6.0),
('b1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000002', 'SQL',                    'SQL',                    'technical',    'expert',       12.0),
('b1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000002', 'FinancialServices',      'Financial Services',     'domain',       'advanced',     14.0),
('b1000000-0000-0000-0000-000000000009', 'a1000000-0000-0000-0000-000000000002', 'PMO',                    'PMO',                    'functional',   'advanced',     5.0),
-- Priya Sharma — Manager, Cloud + Healthcare
('b1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000003', 'AWS',                    'AWS',                    'technical',    'advanced',     5.0),
('b1000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000003', 'Python',                 'Python',                 'technical',    'advanced',     6.0),
('b1000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000003', 'Healthcare',             'Healthcare',             'domain',       'advanced',     7.0),
('b1000000-0000-0000-0000-000000000013', 'a1000000-0000-0000-0000-000000000003', 'ChangeManagement',       'Change Management',      'functional',   'advanced',     4.0),
('b1000000-0000-0000-0000-000000000014', 'a1000000-0000-0000-0000-000000000003', 'StakeholderManagement',  'Stakeholder Management', 'leadership',   'advanced',     5.0),
-- Luca Rossi — Senior Consultant, Full-stack + Retail
('b1000000-0000-0000-0000-000000000015', 'a1000000-0000-0000-0000-000000000004', 'React',                  'React',                  'technical',    'advanced',     4.0),
('b1000000-0000-0000-0000-000000000016', 'a1000000-0000-0000-0000-000000000004', 'TypeScript',             'TypeScript',             'technical',    'advanced',     3.0),
('b1000000-0000-0000-0000-000000000017', 'a1000000-0000-0000-0000-000000000004', 'Java',                   'Java',                   'technical',    'expert',       6.0),
('b1000000-0000-0000-0000-000000000018', 'a1000000-0000-0000-0000-000000000004', 'Retail',                 'Retail',                 'domain',       'intermediate', 3.0),
-- Sophie Müller — Consultant, Data + Energy
('b1000000-0000-0000-0000-000000000019', 'a1000000-0000-0000-0000-000000000005', 'SQL',                    'SQL',                    'technical',    'intermediate', 2.0),
('b1000000-0000-0000-0000-000000000020', 'a1000000-0000-0000-0000-000000000005', 'Python',                 'Python',                 'technical',    'intermediate', 2.0),
('b1000000-0000-0000-0000-000000000021', 'a1000000-0000-0000-0000-000000000005', 'Energy',                 'Energy',                 'domain',       'intermediate', 2.0),
('b1000000-0000-0000-0000-000000000022', 'a1000000-0000-0000-0000-000000000005', 'BusinessAnalysis',       'Business Analysis',      'functional',   'intermediate', 2.0),
-- James Whitfield — Director, Strategy + FinServ
('b1000000-0000-0000-0000-000000000023', 'a1000000-0000-0000-0000-000000000006', 'StrategyConsulting',     'Strategy Consulting',    'functional',   'expert',       14.0),
('b1000000-0000-0000-0000-000000000024', 'a1000000-0000-0000-0000-000000000006', 'FinancialServices',      'Financial Services',     'domain',       'expert',       16.0),
('b1000000-0000-0000-0000-000000000025', 'a1000000-0000-0000-0000-000000000006', 'TeamLeadership',         'Team Leadership',        'leadership',   'expert',       12.0),
('b1000000-0000-0000-0000-000000000026', 'a1000000-0000-0000-0000-000000000006', 'Banking',                'Banking',                'domain',       'expert',       16.0),
-- Maria Gonzalez — Senior Consultant, ML + FinServ
('b1000000-0000-0000-0000-000000000027', 'a1000000-0000-0000-0000-000000000007', 'MachineLearning',        'Machine Learning',       'technical',    'advanced',     5.0),
('b1000000-0000-0000-0000-000000000028', 'a1000000-0000-0000-0000-000000000007', 'Python',                 'Python',                 'technical',    'expert',       6.0),
('b1000000-0000-0000-0000-000000000029', 'a1000000-0000-0000-0000-000000000007', 'SQL',                    'SQL',                    'technical',    'advanced',     5.0),
('b1000000-0000-0000-0000-000000000030', 'a1000000-0000-0000-0000-000000000007', 'FinancialServices',      'Financial Services',     'domain',       'intermediate', 4.0),
('b1000000-0000-0000-0000-000000000031', 'a1000000-0000-0000-0000-000000000007', 'NLP',                    'Natural Language Processing','technical', 'intermediate', 2.0),
-- Derek Chen — Analyst
('b1000000-0000-0000-0000-000000000032', 'a1000000-0000-0000-0000-000000000008', 'Python',                 'Python',                 'technical',    'intermediate', 1.5),
('b1000000-0000-0000-0000-000000000033', 'a1000000-0000-0000-0000-000000000008', 'SQL',                    'SQL',                    'technical',    'intermediate', 1.5),
('b1000000-0000-0000-0000-000000000034', 'a1000000-0000-0000-0000-000000000008', 'BusinessAnalysis',       'Business Analysis',      'functional',   'beginner',     1.0),
-- Kavya Nair — Manager, Cloud + APAC
('b1000000-0000-0000-0000-000000000035', 'a1000000-0000-0000-0000-000000000009', 'GCP',                    'Google Cloud Platform',  'technical',    'advanced',     4.0),
('b1000000-0000-0000-0000-000000000036', 'a1000000-0000-0000-0000-000000000009', 'AWS',                    'AWS',                    'technical',    'intermediate', 3.0),
('b1000000-0000-0000-0000-000000000037', 'a1000000-0000-0000-0000-000000000009', 'PMO',                    'PMO',                    'functional',   'advanced',     4.0),
('b1000000-0000-0000-0000-000000000038', 'a1000000-0000-0000-0000-000000000009', 'Technology',             'Technology',             'domain',       'advanced',     8.0),
('b1000000-0000-0000-0000-000000000039', 'a1000000-0000-0000-0000-000000000009', 'TeamLeadership',         'Team Leadership',        'leadership',   'advanced',     3.0),
-- Rajan Mehta — Senior Consultant, Data + Finance
('b1000000-0000-0000-0000-000000000040', 'a1000000-0000-0000-0000-000000000010', 'Spark',                  'Apache Spark',           'technical',    'advanced',     4.0),
('b1000000-0000-0000-0000-000000000041', 'a1000000-0000-0000-0000-000000000010', 'SQL',                    'SQL',                    'technical',    'expert',       5.0),
('b1000000-0000-0000-0000-000000000042', 'a1000000-0000-0000-0000-000000000010', 'Python',                 'Python',                 'technical',    'advanced',     5.0),
('b1000000-0000-0000-0000-000000000043', 'a1000000-0000-0000-0000-000000000010', 'Banking',                'Banking',                'domain',       'intermediate', 3.0),
-- Olivia Thompson — Consultant, UX + Retail
('b1000000-0000-0000-0000-000000000044', 'a1000000-0000-0000-0000-000000000011', 'React',                  'React',                  'technical',    'intermediate', 2.0),
('b1000000-0000-0000-0000-000000000045', 'a1000000-0000-0000-0000-000000000011', 'TypeScript',             'TypeScript',             'technical',    'intermediate', 2.0),
('b1000000-0000-0000-0000-000000000046', 'a1000000-0000-0000-0000-000000000011', 'Retail',                 'Retail',                 'domain',       'intermediate', 3.0),
('b1000000-0000-0000-0000-000000000047', 'a1000000-0000-0000-0000-000000000011', 'ChangeManagement',       'Change Management',      'functional',   'beginner',     1.0),
-- Wei Zhang — Analyst
('b1000000-0000-0000-0000-000000000048', 'a1000000-0000-0000-0000-000000000012', 'Python',                 'Python',                 'technical',    'beginner',     1.0),
('b1000000-0000-0000-0000-000000000049', 'a1000000-0000-0000-0000-000000000012', 'SQL',                    'SQL',                    'technical',    'beginner',     1.0),
('b1000000-0000-0000-0000-000000000050', 'a1000000-0000-0000-0000-000000000012', 'Technology',             'Technology',             'domain',       'beginner',     1.0);

-- =============================================================================
-- CERTIFICATIONS
-- =============================================================================
INSERT INTO certifications (id, person_id, name, issuer, issued_date, expiry_date) VALUES
('c1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001', 'TOGAF 9.2',                            'The Open Group',                    '2019-03-15', '2025-03-14'),
('c1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000001', 'CFA Level III',                        'CFA Institute',                     '2010-09-01', NULL),
('c1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000002', 'AWS Certified Solutions Architect',    'Amazon Web Services',               '2023-05-20', '2026-05-19'),
('c1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000002', 'PMP',                                  'Project Management Institute',      '2021-11-10', '2024-11-09'),
('c1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000003', 'AWS Certified Solutions Architect',    'Amazon Web Services',               '2024-02-14', '2027-02-13'),
('c1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000003', 'Certified Scrum Master',               'Scrum Alliance',                    '2023-06-01', '2025-05-31'),
('c1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000004', 'Oracle Certified Professional Java SE','Oracle',                            '2022-08-22', NULL),
('c1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000005', 'Microsoft Azure Fundamentals',         'Microsoft',                         '2024-01-09', NULL),
('c1000000-0000-0000-0000-000000000009', 'a1000000-0000-0000-0000-000000000006', 'CFA Level III',                        'CFA Institute',                     '2012-09-01', NULL),
('c1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000006', 'PMP',                                  'Project Management Institute',      '2022-04-05', '2025-04-04'),
('c1000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000007', 'Google Professional Data Engineer',    'Google Cloud',                      '2024-03-11', '2026-03-10'),
('c1000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000007', 'AWS Certified Machine Learning',       'Amazon Web Services',               '2023-09-22', '2026-09-21'),
('c1000000-0000-0000-0000-000000000013', 'a1000000-0000-0000-0000-000000000009', 'Google Professional Cloud Architect',  'Google Cloud',                      '2023-07-14', '2025-07-13'),
('c1000000-0000-0000-0000-000000000014', 'a1000000-0000-0000-0000-000000000009', 'PMP',                                  'Project Management Institute',      '2023-01-20', '2026-01-19'),
('c1000000-0000-0000-0000-000000000015', 'a1000000-0000-0000-0000-000000000010', 'Databricks Certified Data Engineer',   'Databricks',                        '2024-05-30', '2026-05-29'),
('c1000000-0000-0000-0000-000000000016', 'a1000000-0000-0000-0000-000000000011', 'Certified Scrum Master',               'Scrum Alliance',                    '2024-08-01', '2026-07-31');

-- =============================================================================
-- QUALIFICATIONS
-- =============================================================================
INSERT INTO qualifications (id, person_id, degree, institution, field_of_study, graduation_year, level) VALUES
('d1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000001', 'MBA',                          'London Business School',            'Finance',                          2005, 'master'),
('d1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000001', 'BSc Economics',                'University of Edinburgh',           'Economics',                        2002, 'bachelor'),
('d1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000002', 'MSc Computer Science',         'Technical University of Munich',    'Computer Science',                 2010, 'master'),
('d1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000003', 'MSc Data Science',             'University College London',         'Data Science',                     2016, 'master'),
('d1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000003', 'BEng Computer Science',        'University of Warwick',             'Computer Science',                 2014, 'bachelor'),
('d1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000004', 'BSc Software Engineering',     'Politecnico di Milano',             'Software Engineering',             2019, 'bachelor'),
('d1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000005', 'BSc Business Informatics',     'Goethe University Frankfurt',       'Business Informatics',             2022, 'bachelor'),
('d1000000-0000-0000-0000-000000000008', 'a1000000-0000-0000-0000-000000000006', 'MBA',                          'Wharton School, University of Pennsylvania', 'Finance & Strategy',    2008, 'master'),
('d1000000-0000-0000-0000-000000000009', 'a1000000-0000-0000-0000-000000000006', 'BA Economics',                 'Yale University',                   'Economics',                        2005, 'bachelor'),
('d1000000-0000-0000-0000-000000000010', 'a1000000-0000-0000-0000-000000000007', 'MS Applied Mathematics',       'Columbia University',               'Applied Mathematics',              2018, 'master'),
('d1000000-0000-0000-0000-000000000011', 'a1000000-0000-0000-0000-000000000008', 'BS Computer Science',          'NYU Tandon School of Engineering',  'Computer Science',                 2024, 'bachelor'),
('d1000000-0000-0000-0000-000000000012', 'a1000000-0000-0000-0000-000000000009', 'MBA',                          'INSEAD',                            'Strategy & Technology',            2017, 'master'),
('d1000000-0000-0000-0000-000000000013', 'a1000000-0000-0000-0000-000000000010', 'BTech Computer Science',       'IIT Bombay',                        'Computer Science',                 2020, 'bachelor'),
('d1000000-0000-0000-0000-000000000014', 'a1000000-0000-0000-0000-000000000011', 'BCom Information Systems',     'University of Sydney',              'Information Systems',              2022, 'bachelor'),
('d1000000-0000-0000-0000-000000000015', 'a1000000-0000-0000-0000-000000000012', 'BSc Computer Science',         'National University of Singapore',  'Computer Science',                 2025, 'bachelor');

-- =============================================================================
-- PROJECTS  (4 projects across industries)
-- =============================================================================
INSERT INTO project (id, unique_code, client, project_name, start_date, end_date, industry, sector, function, region, status) VALUES
('e1000000-0000-0000-0000-000000000001', 'PROJ-FT-2025-001', 'NovaPay Financial',          'Core Banking Modernisation',         '2025-01-15', '2026-06-30', 'FinTech',     'Banking',     'Technology',       'EMEA',     'active'),
('e1000000-0000-0000-0000-000000000002', 'PROJ-HC-2025-002', 'MedCore NHS Trust',          'Digital Health Records Platform',    '2025-04-01', '2026-09-30', 'Healthcare',  'Public',      'Technology',       'EMEA',     'active'),
('e1000000-0000-0000-0000-000000000003', 'PROJ-EN-2024-003', 'GreenVolt Energy',           'Smart Grid Analytics Programme',     '2024-06-01', '2025-12-31', 'Energy',      'Utilities',   'Analytics',        'Americas', 'completed'),
('e1000000-0000-0000-0000-000000000004', 'PROJ-RT-2026-004', 'GlobalMart Retail Group',    'Omnichannel Commerce Transformation','2026-03-01', '2027-02-28', 'Retail',      'Consumer',    'Strategy',         'APAC',     'active');

-- =============================================================================
-- LEADERSHIP
-- =============================================================================
INSERT INTO leadership (id, project_id, role, person_id) VALUES
('f1000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000001', 'engagement_partner', 'a1000000-0000-0000-0000-000000000001'),
('f1000000-0000-0000-0000-000000000002', 'e1000000-0000-0000-0000-000000000001', 'delivery_lead',      'a1000000-0000-0000-0000-000000000002'),
('f1000000-0000-0000-0000-000000000003', 'e1000000-0000-0000-0000-000000000002', 'engagement_partner', 'a1000000-0000-0000-0000-000000000001'),
('f1000000-0000-0000-0000-000000000004', 'e1000000-0000-0000-0000-000000000002', 'delivery_lead',      'a1000000-0000-0000-0000-000000000003'),
('f1000000-0000-0000-0000-000000000005', 'e1000000-0000-0000-0000-000000000003', 'engagement_partner', 'a1000000-0000-0000-0000-000000000006'),
('f1000000-0000-0000-0000-000000000006', 'e1000000-0000-0000-0000-000000000003', 'delivery_lead',      'a1000000-0000-0000-0000-000000000002'),
('f1000000-0000-0000-0000-000000000007', 'e1000000-0000-0000-0000-000000000004', 'engagement_partner', 'a1000000-0000-0000-0000-000000000006'),
('f1000000-0000-0000-0000-000000000008', 'e1000000-0000-0000-0000-000000000004', 'delivery_lead',      'a1000000-0000-0000-0000-000000000009');

-- =============================================================================
-- TEAMS
-- =============================================================================
INSERT INTO team (id, project_id, name, team_lead_id) VALUES
-- NovaPay — Core Banking
('g1000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000001', 'Core Banking Data Team',         'a1000000-0000-0000-0000-000000000002'),
('g1000000-0000-0000-0000-000000000002', 'e1000000-0000-0000-0000-000000000001', 'Integration & API Team',          'a1000000-0000-0000-0000-000000000003'),
-- MedCore — Digital Health
('g1000000-0000-0000-0000-000000000003', 'e1000000-0000-0000-0000-000000000002', 'Platform Engineering Team',       'a1000000-0000-0000-0000-000000000003'),
('g1000000-0000-0000-0000-000000000004', 'e1000000-0000-0000-0000-000000000002', 'Data & Analytics Team',           'a1000000-0000-0000-0000-000000000009'),
-- GreenVolt — Smart Grid (completed)
('g1000000-0000-0000-0000-000000000005', 'e1000000-0000-0000-0000-000000000003', 'Smart Grid Analytics Team',       'a1000000-0000-0000-0000-000000000002'),
-- GlobalMart — Omnichannel Retail
('g1000000-0000-0000-0000-000000000006', 'e1000000-0000-0000-0000-000000000004', 'Strategy & Design Team',          'a1000000-0000-0000-0000-000000000009'),
('g1000000-0000-0000-0000-000000000007', 'e1000000-0000-0000-0000-000000000004', 'Frontend Delivery Team',          'a1000000-0000-0000-0000-000000000004');

-- =============================================================================
-- OPPORTUNITIES
-- =============================================================================
INSERT INTO opportunity (id, team_id, role_title, band_required, start_date, end_date, status) VALUES
-- NovaPay: Core Banking Data Team — need Senior Data Engineer
('h1000000-0000-0000-0000-000000000001', 'g1000000-0000-0000-0000-000000000001', 'Senior Data Engineer',        'Senior Consultant', '2025-07-01', '2026-06-30', 'filled'),
-- NovaPay: Integration & API Team — need Java Backend Engineer
('h1000000-0000-0000-0000-000000000002', 'g1000000-0000-0000-0000-000000000002', 'Java Backend Engineer',       'Consultant',        '2025-07-01', '2026-06-30', 'filled'),
-- MedCore: Platform Engineering — need Cloud Architect
('h1000000-0000-0000-0000-000000000003', 'g1000000-0000-0000-0000-000000000003', 'Cloud Solutions Architect',   'Manager',           '2025-06-01', '2026-09-30', 'filled'),
-- MedCore: Data & Analytics — need Data Analyst (open)
('h1000000-0000-0000-0000-000000000004', 'g1000000-0000-0000-0000-000000000004', 'Data Analyst',                'Analyst',           '2026-07-01', '2026-09-30', 'open'),
-- GlobalMart: Strategy — need Strategy Manager (open)
('h1000000-0000-0000-0000-000000000005', 'g1000000-0000-0000-0000-000000000006', 'Strategy Manager',            'Manager',           '2026-06-15', '2026-12-31', 'open'),
-- GlobalMart: Frontend — need React Developer (cancelled)
('h1000000-0000-0000-0000-000000000006', 'g1000000-0000-0000-0000-000000000007', 'React Frontend Developer',    'Consultant',        '2026-03-01', '2026-08-31', 'cancelled'),
-- GlobalMart: Frontend — new React Developer slot (open)
('h1000000-0000-0000-0000-000000000007', 'g1000000-0000-0000-0000-000000000007', 'React Frontend Developer',    'Consultant',        '2026-07-01', '2027-02-28', 'open');

-- =============================================================================
-- OPPORTUNITY_SKILL
-- =============================================================================
INSERT INTO opportunity_skill (id, opportunity_id, skill_name, skill_type, is_mandatory) VALUES
-- h1 Senior Data Engineer
('i1000000-0000-0000-0000-000000000001', 'h1000000-0000-0000-0000-000000000001', 'Apache Spark',     'technical',  true),
('i1000000-0000-0000-0000-000000000002', 'h1000000-0000-0000-0000-000000000001', 'SQL',              'technical',  true),
('i1000000-0000-0000-0000-000000000003', 'h1000000-0000-0000-0000-000000000001', 'Python',           'technical',  false),
('i1000000-0000-0000-0000-000000000004', 'h1000000-0000-0000-0000-000000000001', 'Financial Services','domain',    false),
-- h2 Java Backend Engineer
('i1000000-0000-0000-0000-000000000005', 'h1000000-0000-0000-0000-000000000002', 'Java',             'technical',  true),
('i1000000-0000-0000-0000-000000000006', 'h1000000-0000-0000-0000-000000000002', 'React',            'technical',  false),
-- h3 Cloud Solutions Architect
('i1000000-0000-0000-0000-000000000007', 'h1000000-0000-0000-0000-000000000003', 'AWS',              'technical',  true),
('i1000000-0000-0000-0000-000000000008', 'h1000000-0000-0000-0000-000000000003', 'Healthcare',       'domain',     true),
('i1000000-0000-0000-0000-000000000009', 'h1000000-0000-0000-0000-000000000003', 'Change Management','functional', false),
-- h4 Data Analyst
('i1000000-0000-0000-0000-000000000010', 'h1000000-0000-0000-0000-000000000004', 'SQL',              'technical',  true),
('i1000000-0000-0000-0000-000000000011', 'h1000000-0000-0000-0000-000000000004', 'Python',           'technical',  false),
-- h5 Strategy Manager
('i1000000-0000-0000-0000-000000000012', 'h1000000-0000-0000-0000-000000000005', 'Strategy Consulting','functional',true),
('i1000000-0000-0000-0000-000000000013', 'h1000000-0000-0000-0000-000000000005', 'Retail',           'domain',     false),
-- h7 React Frontend Developer
('i1000000-0000-0000-0000-000000000014', 'h1000000-0000-0000-0000-000000000007', 'React',            'technical',  true),
('i1000000-0000-0000-0000-000000000015', 'h1000000-0000-0000-0000-000000000007', 'TypeScript',       'technical',  true),
('i1000000-0000-0000-0000-000000000016', 'h1000000-0000-0000-0000-000000000007', 'Retail',           'domain',     false);

-- =============================================================================
-- OPPORTUNITY_QUALIFICATION
-- =============================================================================
INSERT INTO opportunity_qualification (id, opportunity_id, qualification_level, field_of_study, is_mandatory) VALUES
('j1000000-0000-0000-0000-000000000001', 'h1000000-0000-0000-0000-000000000001', 'bachelor', 'Computer Science',  true),
('j1000000-0000-0000-0000-000000000002', 'h1000000-0000-0000-0000-000000000003', 'master',   NULL,                false),
('j1000000-0000-0000-0000-000000000003', 'h1000000-0000-0000-0000-000000000005', 'master',   'Business',          false);

-- =============================================================================
-- ASSIGNMENTS
-- =============================================================================
-- actor: Amelia Hartley (a1) or Thomas Becker (a2) as assigned_by
INSERT INTO assignment (id, opportunity_id, person_id, start_date, end_date, status, notes, assigned_by, assigned_at) VALUES
-- Rajan → Senior Data Engineer on NovaPay (staffed)
('k1000000-0000-0000-0000-000000000001', 'h1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000010',
 '2025-07-01', '2026-06-30', 'staffed',      'Strong Spark background; passed technical screening.',
 'a1000000-0000-0000-0000-000000000002', '2025-06-10 09:00:00+00'),
-- Luca → Java Backend Engineer on NovaPay (staffed)
('k1000000-0000-0000-0000-000000000002', 'h1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000004',
 '2025-07-01', '2026-06-30', 'staffed',      'Excellent Java OCP; good fit for microservices layer.',
 'a1000000-0000-0000-0000-000000000002', '2025-06-11 10:30:00+00'),
-- Priya → Cloud Solutions Architect on MedCore (staffed)
('k1000000-0000-0000-0000-000000000003', 'h1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000003',
 '2025-06-01', '2026-09-30', 'staffed',      'AWS certified; domain experience in healthcare.',
 'a1000000-0000-0000-0000-000000000001', '2025-05-15 14:00:00+00'),
-- Wei → Data Analyst on MedCore (short_listed)
('k1000000-0000-0000-0000-000000000004', 'h1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000012',
 '2026-07-01', '2026-09-30', 'short_listed', 'Recent graduate; SQL skills match; pending partner approval.',
 'a1000000-0000-0000-0000-000000000009', '2026-05-20 11:00:00+00'),
-- Derek → Data Analyst on MedCore (short_listed, additional candidate)
('k1000000-0000-0000-0000-000000000005', 'h1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000008',
 '2026-07-01', '2026-09-30', 'short_listed', 'Also under consideration; Americas timezone preferred.',
 'a1000000-0000-0000-0000-000000000006', '2026-05-22 09:30:00+00'),
-- Olivia → React Frontend Developer on GlobalMart (short_listed)
('k1000000-0000-0000-0000-000000000006', 'h1000000-0000-0000-0000-000000000007', 'a1000000-0000-0000-0000-000000000011',
 '2026-07-01', '2027-02-28', 'short_listed', 'React and TypeScript skills fit; Retail domain knowledge is a plus.',
 'a1000000-0000-0000-0000-000000000009', '2026-05-28 08:00:00+00'),
-- Sophie → cancelled on old React slot
('k1000000-0000-0000-0000-000000000007', 'h1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000005',
 '2026-03-01', '2026-08-31', 'cancelled',    'Opportunity cancelled before engagement started.',
 'a1000000-0000-0000-0000-000000000002', '2026-02-15 10:00:00+00');

-- =============================================================================
-- STAFFING_HISTORY  (past allocations for completed/historical context)
-- =============================================================================
INSERT INTO staffing_history (id, person_id, project_id, role_played, start_date, end_date, allocation_pct, notes) VALUES
-- Thomas Becker on GreenVolt (completed)
('l1000000-0000-0000-0000-000000000001', 'a1000000-0000-0000-0000-000000000002', 'e1000000-0000-0000-0000-000000000003',
 'Delivery Lead',           '2024-06-01', '2025-12-31', 100.00, 'Led smart grid analytics delivery end-to-end.'),
-- Sophie Müller on GreenVolt
('l1000000-0000-0000-0000-000000000002', 'a1000000-0000-0000-0000-000000000005', 'e1000000-0000-0000-0000-000000000003',
 'Data Analyst',            '2024-06-01', '2025-12-31', 80.00,  'Contributed to energy data modelling workstream.'),
-- Rajan Mehta on GreenVolt
('l1000000-0000-0000-0000-000000000003', 'a1000000-0000-0000-0000-000000000010', 'e1000000-0000-0000-0000-000000000003',
 'Senior Data Engineer',    '2024-09-01', '2025-12-31', 100.00, 'Built Spark pipelines for smart meter ingestion.'),
-- Amelia Hartley on NovaPay (historical oversight role)
('l1000000-0000-0000-0000-000000000004', 'a1000000-0000-0000-0000-000000000001', 'e1000000-0000-0000-0000-000000000001',
 'Engagement Partner',      '2025-01-15', NULL,          20.00,  'Ongoing senior oversight; not a day-to-day role.'),
-- Kavya Nair — prior project before GlobalMart
('l1000000-0000-0000-0000-000000000005', 'a1000000-0000-0000-0000-000000000009', 'e1000000-0000-0000-0000-000000000002',
 'Delivery Lead',           '2025-04-01', NULL,          50.00,  'Leading Data & Analytics sub-team on MedCore.'),
-- Maria Gonzalez — short past project
('l1000000-0000-0000-0000-000000000006', 'a1000000-0000-0000-0000-000000000007', 'e1000000-0000-0000-0000-000000000003',
 'ML Engineer',             '2024-10-01', '2025-12-31', 100.00, 'Developed anomaly detection models for GreenVolt grid data.');

-- =============================================================================
-- PROV_LOG  (sample provenance entries)
-- =============================================================================
INSERT INTO prov_log (id, entity_type, entity_id, action, actor_id, timestamp, payload, reason) VALUES
('m1000000-0000-0000-0000-000000000001',
 'assignment', 'k1000000-0000-0000-0000-000000000003',
 'INSERT',
 'a1000000-0000-0000-0000-000000000001',
 '2025-05-15 14:00:00+00',
 '{"opportunity_id":"h1000000-0000-0000-0000-000000000003","person_id":"a1000000-0000-0000-0000-000000000003","status":"staffed"}'::jsonb,
 'Approved by Engagement Partner after skills review; AWS certification verified.'),

('m1000000-0000-0000-0000-000000000002',
 'assignment', 'k1000000-0000-0000-0000-000000000001',
 'INSERT',
 'a1000000-0000-0000-0000-000000000002',
 '2025-06-10 09:00:00+00',
 '{"opportunity_id":"h1000000-0000-0000-0000-000000000001","person_id":"a1000000-0000-0000-0000-000000000010","status":"staffed"}'::jsonb,
 'Delivery lead approved: Spark and SQL competencies confirmed via Databricks cert.'),

('m1000000-0000-0000-0000-000000000003',
 'assignment', 'k1000000-0000-0000-0000-000000000007',
 'UPDATE',
 'a1000000-0000-0000-0000-000000000002',
 '2026-02-15 10:00:00+00',
 '{"opportunity_id":"h1000000-0000-0000-0000-000000000006","person_id":"a1000000-0000-0000-0000-000000000005","status":"cancelled"}'::jsonb,
 'Opportunity h6 cancelled by client; GlobalMart deferred frontend work to Q3 2026.');
