CREATE SCHEMA IF NOT EXISTS Marketing
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE Marketing;

CREATE TABLE Brands (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(20) NOT NULL
);

INSERT INTO Brands (name)
VALUES 
('Nurvai'),
('Wexpand'),
('Wexpand Talent');

CREATE TABLE SocialMediaAccounts(
    id INT AUTO_INCREMENT PRIMARY KEY,
    brand_id INT NOT NULL,
    channel VARCHAR(20) NOT NULL,

    CONSTRAINT account_brand
        FOREIGN KEY (brand_id)
        REFERENCES Brands(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT unique_account
        UNIQUE (brand_id, channel),
    
    CONSTRAINT chk_channel
        CHECK (channel <> '')
);

INSERT INTO SocialMediaAccounts (channel, brand_id)
VALUES 
('X',1),
('LinkedIn',1),
('LinkedIn',2),
('LinkedIn',3),
('Instagram',3);

CREATE TABLE StrategyPillars(
    id INT AUTO_INCREMENT PRIMARY KEY,
    brand_id INT NOT NULL,
    pillar VARCHAR(50) NOT NULL,

    CONSTRAINT strategy_pillar_brand
        FOREIGN KEY (brand_id)
        REFERENCES Brands(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,

    CONSTRAINT unique_strategy_pillar
        UNIQUE(pillar, brand_id),

    CONSTRAINT chk_strategy_pillar
        CHECK (pillar <> '')
);

INSERT INTO StrategyPillars (brand_id, pillar)
VALUES 
(1,'Robotics News'),
(1,'Main Issues/Stopers of data collection'),
(1,'Data Insights'),
(1,'Test/Research'),
(1,'Behind the Scenes'),
(1,'Amplification of External Knowledge'),
(3,'Inside Wexpand (Vida y Cultura)'),
(3,'Crecimiento & Academia'),
(3,'People-First & Wellness'),
(3,'Human Touch'),
(3,'Global Exposure'),
(2,'Why Mexico'),
(2,'Future Ready and High Performance Talent'),
(2,'Compliance & Legal Expertise'),
(2,'HR Experience'),
(2,'Proof & Trust'),
(2,'Commercial Awareness');

CREATE TABLE ContentPillars (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pillar VARCHAR(20) NOT NULL,

    CONSTRAINT unique_content_pillar
        UNIQUE (pillar),

    CONSTRAINT chk_content_pillar
        CHECK (pillar <> '')
);

INSERT INTO ContentPillars (pillar)
VALUES 
('Value'),
('Educational'),
('Promotional'),
('Creative/Inspiring');

CREATE TABLE Formats(
    id INT AUTO_INCREMENT PRIMARY KEY,
    format VARCHAR(32) NOT NULL,

    CONSTRAINT unique_format
        UNIQUE(format),

    CONSTRAINT chk_format
        CHECK (format <> '')
);

INSERT INTO Formats (format)
VALUES 
('Tweet (2 Lines)'),
('Repost With Text'),
('Single Text Post'),
('Picture & Text'),
('Blog/Article/Newsletter'),
('Carousel'),
('Storie'),
('Reply'),
('Short Video/Reel'),
('Downloadable'),
('Case Study'),
('Thread'),
('Survey');

CREATE TABLE Sources(
    id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(30),
    medium VARCHAR(30),
    campaign VARCHAR(30),
    brand_id INT NOT NULL,

    CONSTRAINT unique_utm
        UNIQUE(source, medium, campaign, brand_id),

    CONSTRAINT source_brand
        FOREIGN KEY (brand_id)
        REFERENCES Brands(id)
);

CREATE TABLE Websites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    url VARCHAR(200) NOT NULL, 
    pageName VARCHAR(20) NOT NULL,
    property_id INT NOT NULL,
    brand_id INT NOT NULL,

    CONSTRAINT unique_page
        UNIQUE(pageName, brand_id),
    
    CONSTRAINT website_brand
        FOREIGN KEY (brand_id)
        REFERENCES Brands(id),

    CONSTRAINT chk_url
        CHECK(url <> ''),

    CONSTRAINT chk_page_name
        CHECK(pageName <> ''),

    CONSTRAINT chk_property_id
        CHECK(property_id > 0)
);

CREATE TABLE Metrics (
    account_id INT NOT NULL,
    bookmarks INT,
    clicks INT,
    comments INT,
    date DATETIME,
    engagementRate DOUBLE,
    engagements INT,
    followersGained INT,
    followersTotal INT,
    impressions INT,
    reactions INT,
    shares INT,
    unfollows INT,
    row_hash VARCHAR(32) PRIMARY KEY,
    updated_at DATETIME,

    CONSTRAINT metric_account
        FOREIGN KEY (account_id)
        REFERENCES SocialMediaAccounts(id)
);

CREATE TABLE Posts (
    postText TEXT,
    postUrl VARCHAR(100),
    format_id INT,
    content_pillar_id INT,
    strategy_pillar_id INT,
    date DATETIME,
    impressions INT,
    views INT,
    clicks INT,
    clickThroughRate DOUBLE,
    reactions INT,
    comments INT,
    shares INT,
    followersGained INT,
    engagementRate DOUBLE,
    engagements INT,
    bookmarks INT,
    profileVisits INT,
    detailExpands INT,
    urlClicks INT,
    hashtagClicks INT,
    permalinkClicks INT,
    account_id INT NOT NULL,
    umap_x DOUBLE,
    umap_y DOUBLE,
    row_hash VARCHAR(32) PRIMARY KEY,
    updated_at DATETIME,

    CONSTRAINT post_account
        FOREIGN KEY (account_id)
        REFERENCES SocialMediaAccounts(id),
    
    CONSTRAINT post_format
        FOREIGN KEY (format_id)
        REFERENCES Formats(id),

    CONSTRAINT post_content_pillar
        FOREIGN KEY (content_pillar_id)
        REFERENCES ContentPillars(id),

    CONSTRAINT post_strategy_pillar
        FOREIGN KEY (strategy_pillar_id)
        REFERENCES StrategyPillars(id)
);

CREATE TABLE Terms (
    term VARCHAR(300),
    engagement_score DOUBLE,
    account_id INT,
    row_hash VARCHAR(32) PRIMARY KEY,
    updated_at DATETIME,

    CONSTRAINT term_account
        FOREIGN KEY (account_id) 
        REFERENCES SocialMediaAccounts(id)
);

