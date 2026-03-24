"""
run_phase3a1_production.py — Phase 3A.1 Team-Only Production Pricing
Mean layer: P2_30 — KenPom backbone + λ=0.30 BDB recency residual
  oe = KP_AdjOE + 0.30*(blend_OEFF - BDB_lg_sym)
  de = KP_AdjDE + 0.30*(blend_DEFF - BDB_lg_sym)
  tp = KP_AdjTempo + 0.20*(blend_POSS  - BDB_lg_tp)
  blg = kp_lg_sym

Ablation 2026-03-21: P0 SD=2.874 corr=0.654 REJECTED | P2_30 corr=0.950 SELECTED
"""
from __future__ import annotations
import sys, math, argparse, logging
from pathlib import Path
import numpy as np, pandas as pd
from scipy import special, optimize

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger("prod3a1")

PHI,SIG,NQ,MX = 0.004,0.085,9,130
WO,WD = 0.55,0.45
LAM_OE,LAM_DE,LAM_TP = 0.30,0.30,0.20

XWALK = {
    "Iowa State Cyclones":"Iowa St.","Miami Hurricanes":"Miami FL",
    "New Mexico Lobos":"New Mexico","UConn Huskies":"Connecticut",
    "UNLV Rebels":"UNLV","Utah State Aggies":"Utah St.",
    "Vanderbilt Commodores":"Vanderbilt","Virginia Cavaliers":"Virginia",
    "Alabama Crimson Tide":"Alabama","Arizona Wildcats":"Arizona",
    "Arizona State Sun Devils":"Arizona St.","Arkansas Razorbacks":"Arkansas",
    "Auburn Tigers":"Auburn","Baylor Bears":"Baylor","BYU Cougars":"BYU",
    "Colorado State Rams":"Colorado St.","Connecticut Huskies":"Connecticut",
    "Duke Blue Devils":"Duke","Florida Gators":"Florida",
    "Florida State Seminoles":"Florida St.","Georgia Bulldogs":"Georgia",
    "Georgia Tech Yellow Jackets":"Georgia Tech","Gonzaga Bulldogs":"Gonzaga",
    "Houston Cougars":"Houston","Illinois Fighting Illini":"Illinois",
    "Indiana Hoosiers":"Indiana","Iowa Hawkeyes":"Iowa","Kansas Jayhawks":"Kansas",
    "Kansas State Wildcats":"Kansas St.","Kentucky Wildcats":"Kentucky",
    "LSU Tigers":"LSU","Louisville Cardinals":"Louisville",
    "Marquette Golden Eagles":"Marquette","Maryland Terrapins":"Maryland",
    "Memphis Tigers":"Memphis","Michigan Wolverines":"Michigan",
    "Michigan State Spartans":"Michigan St.","Michigan St Spartans":"Michigan St.",
    "Minnesota Golden Gophers":"Minnesota","Mississippi Rebels":"Mississippi",
    "Ole Miss Rebels":"Mississippi","Mississippi State Bulldogs":"Mississippi St.",
    "Missouri Tigers":"Missouri","NC State Wolfpack":"N.C. State",
    "North Carolina Tar Heels":"North Carolina","Northwestern Wildcats":"Northwestern",
    "Notre Dame Fighting Irish":"Notre Dame","Ohio State Buckeyes":"Ohio St.",
    "Oklahoma Sooners":"Oklahoma","Oklahoma State Cowboys":"Oklahoma St.",
    "Oregon Ducks":"Oregon","Oregon State Beavers":"Oregon St.",
    "Penn State Nittany Lions":"Penn St.","Pittsburgh Panthers":"Pittsburgh",
    "Purdue Boilermakers":"Purdue","Rutgers Scarlet Knights":"Rutgers",
    "San Diego State Aztecs":"San Diego St.","South Carolina Gamecocks":"South Carolina",
    "Stanford Cardinal":"Stanford","Syracuse Orange":"Syracuse",
    "TCU Horned Frogs":"TCU","Tennessee Volunteers":"Tennessee",
    "Texas Longhorns":"Texas","Texas A&M Aggies":"Texas A&M",
    "Texas Tech Red Raiders":"Texas Tech","UCLA Bruins":"UCLA","USC Trojans":"USC",
    "Utah Utes":"Utah","Virginia Tech Hokies":"Virginia Tech",
    "Wake Forest Demon Deacons":"Wake Forest","Washington Huskies":"Washington",
    "Washington State Cougars":"Washington St.",
    "West Virginia Mountaineers":"West Virginia","Wisconsin Badgers":"Wisconsin",
    "Xavier Musketeers":"Xavier","High Point Panthers":"High Point",
    "Seattle Redhawks":"Seattle","Seattle U Redhawks":"Seattle",
    "Saint Joseph's Hawks":"Saint Joseph's","St. Joseph's Hawks":"Saint Joseph's",
    "California Golden Bears":"California",
    "George Washington Revolutionaries":"George Washington",
    "SE Louisiana Lions":"Southeastern Louisiana",
    "San José State Spartans":"San Jose St.",
    "UL Monroe Warhawks":"Louisiana Monroe",
    "Hawai'i Rainbow Warriors":"Hawaii",
    "UIC Flames":"Illinois Chicago",
    "Omaha Mavericks":"Nebraska Omaha",
    "USC Upstate Spartans":"USC Upstate",
    "UNO Mavericks":"Nebraska Omaha",
    "ULM Warhawks":"Louisiana Monroe",
    "UAlbany Great Danes":"Albany",
    "Tarleton Texans":"Tarleton St.",
    "Southeastern Louisiana Lions":"Southeastern Louisiana",
    "San Jose State Spartans":"San Jose St.",
    "SIUE Cougars":"SIUE",
    "Nebraska-Omaha Mavericks":"Nebraska Omaha",
    "Miami (OH) RedHawks":"Miami OH",
    "Loyola Maryland Greyhounds":"Loyola MD",
    "Louisiana Monroe Warhawks":"Louisiana Monroe",
    "Long Beach State 49ers":"Long Beach St.",
    "LIU Sharks":"LIU",
    "Illinois Chicago Flames":"Illinois Chicago",
    "IU Indianapolis Jaguars":"IU Indy",
    "Hawaii Warriors":"Hawaii",
    "Hawaii Rainbow Warriors":"Hawaii",
    "Grambling Tigers":"Grambling St.",
    "Gardner-Webb Bulldogs":"Gardner Webb",
    "FIU Panthers":"FIU",
    "Cal State Northridge Matadors":"CSUN",
    "Cal Baptist Lancers":"Cal Baptist",
    "CS Northridge Matadors":"CSUN",
    "App State Mountaineers":"Appalachian St.",
    "Youngstown State Penguins":"Youngstown St.",
    "Wright State Raiders":"Wright St.",
    "Wichita State Shockers":"Wichita St.",
    "Weber State Wildcats":"Weber St.",
    "UT Martin Skyhawks":"Tennessee Martin",
    "Tarleton State Texans":"Tarleton St.",
    "Sacramento State Hornets":"Sacramento St.",
    "SIU Edwardsville Cougars":"SIUE",
    "Norfolk State Spartans":"Norfolk St.",
    "Murray State Racers":"Murray St.",
    "Morgan State Bears":"Morgan St.",
    "Morehead State Eagles":"Morehead St.",
    "Long Island University Sharks":"LIU",
    "Long Beach State Beach":"Long Beach St.",
    "Kent State Golden Flashes":"Kent St.",
    "Kennesaw State Owls":"Kennesaw St.",
    "Jackson State Tigers":"Jackson St.",
    "Gardner-Webb Runnin' Bulldogs":"Gardner Webb",
    "Fresno State Bulldogs":"Fresno St.",
    "East Tennessee State Buccaneers":"East Tennessee St.",
    "Coppin State Eagles":"Coppin St.",
    "Cleveland State Vikings":"Cleveland St.",
    "Chicago State Cougars":"Chicago St.",
    "Cal State Fullerton Titans":"Cal St. Fullerton",
    "Cal State Bakersfield Roadrunners":"Cal St. Bakersfield",
    "Boise State Broncos":"Boise St.",
    "Bethune-Cookman Wildcats":"Bethune Cookman",
    "Ball State Cardinals":"Ball St.",
    "Arkansas-Pine Bluff Golden Lions":"Arkansas Pine Bluff",
    "Alcorn State Braves":"Alcorn St.",
    "Yale Bulldogs":"Yale",
    "Wyoming Cowboys":"Wyoming",
    "Wofford Terriers":"Wofford",
    "Winthrop Eagles":"Winthrop",
    "William & Mary Tribe":"William & Mary",
    "Western Michigan Broncos":"Western Michigan",
    "Western Kentucky Hilltoppers":"Western Kentucky",
    "Western Illinois Leathernecks":"Western Illinois",
    "Western Carolina Catamounts":"Western Carolina",
    "West Virginia Wesleyan Bobcats":"West Virginia",
    "West Georgia Wolves":"West Georgia",
    "Washington and Lee Generals":"Washington",
    "Washington College (MD) Shoremen":"Washington",
    "Washington Adventist Shock":"Washington",
    "Wagner Seahawks":"Wagner",
    "Virginia St Trojans":"Virginia",
    "Villanova Wildcats":"Villanova",
    "Vermont State - Lyndon Hornets":"Vermont",
    "Vermont State - Johnson Badgers":"Vermont",
    "Vermont Catamounts":"Vermont",
    "Valparaiso Beacons":"Valparaiso",
    "VMI Keydets":"VMI",
    "VCU Rams":"VCU",
    "Utah Valley Wolverines":"Utah Valley",
    "Utah Tech Trailblazers":"Utah Tech",
    "UTSA Roadrunners":"UTSA",
    "UTEP Miners":"UTEP",
    "UT Rio Grande Valley Vaqueros":"UT Rio Grande Valley",
    "UT Arlington Mavericks":"UT Arlington",
    "UNC Wilmington Seahawks":"UNC Wilmington",
    "UNC Greensboro Spartans":"UNC Greensboro",
    "UNC Asheville Bulldogs":"UNC Asheville",
    "UMass Lowell River Hawks":"UMass Lowell",
    "UMBC Retrievers":"UMBC",
    "UCF Knights":"UCF",
    "UC Santa Barbara Gauchos":"UC Santa Barbara",
    "UC San Diego Tritons":"UC San Diego",
    "UC Riverside Highlanders":"UC Riverside",
    "UC Irvine Anteaters":"UC Irvine",
    "UC Davis Aggies":"UC Davis",
    "UAB Blazers":"UAB",
    "Tulane Green Wave":"Tulane",
    "Troy Trojans":"Troy",
    "Towson Tigers":"Towson",
    "Toledo Rockets":"Toledo",
    "The Citadel Bulldogs":"The Citadel",
    "Texas State Bobcats":"Texas St.",
    "Texas Southern Tigers":"Texas Southern",
    "Texas Lutheran Bulldogs":"Texas",
    "Texas A&M-San Antonio Jaguars":"Texas",
    "Texas A&M-Corpus Christi Islanders":"Texas A&M Corpus Chris",
    "Tennessee Wesleyan Bulldogs":"Tennessee",
    "Tennessee Tech Golden Eagles":"Tennessee Tech",
    "Tennessee State Tigers":"Tennessee St.",
    "Tennessee Southern Firehawks":"Tennessee",
    "Temple Owls":"Temple",
    "Stony Brook Seawolves":"Stony Brook",
    "Stonehill Skyhawks":"Stonehill",
    "Stetson Hatters":"Stetson",
    "Stephen F. Austin Lumberjacks":"Stephen F. Austin",
    "St. Thomas (TX) Celts":"St. Thomas",
    "St. Bonaventure Bonnies":"St. Bonaventure",
    "Southern Wesleyan Warriors":"Southern",
    "Southern Virginia Knights":"Southern",
    "Southern Utah Thunderbirds":"Southern Utah",
    "Southern Miss Golden Eagles":"Southern Miss",
    "Southern Jaguars":"Southern",
    "Southern Indiana Screaming Eagles":"Southern Indiana",
    "Southern Illinois Salukis":"Southern Illinois",
    "Southern Arkansas Muleriders":"Southern",
    "Southeast Missouri State Redhawks":"Southeast Missouri",
    "South Florida Bulls":"South Florida",
    "South Dakota State Jackrabbits":"South Dakota St.",
    "South Dakota Coyotes":"South Dakota",
    "South Carolina Upstate Spartans":"USC Upstate",
    "South Carolina State Bulldogs":"South Carolina St.",
    "South Alabama Jaguars":"South Alabama",
    "Siena Saints":"Siena",
    "Siena Heights Saints":"Siena",
    "Seton Hall Pirates":"Seton Hall",
    "Santa Clara Broncos":"Santa Clara",
    "San Francisco State Gators":"San Francisco",
    "San Francisco Dons":"San Francisco",
    "San Diego Toreros":"San Diego",
    "Samford Bulldogs":"Samford",
    "Saint Peter's Peacocks":"Saint Peter's",
    "Saint Mary's Gaels":"Saint Mary's",
    "Saint Louis Billikens":"Saint Louis",
    "Saint Francis Red Flash":"Saint Francis",
    "Sacred Heart Pioneers":"Sacred Heart",
    "SMU Mustangs":"SMU",
    "Robert Morris Colonials":"Robert Morris",
    "Rider Broncs":"Rider",
    "Richmond Spiders":"Richmond",
    "Rice Owls":"Rice",
    "Rhode Island Rams":"Rhode Island",
    "Radford Highlanders":"Radford",
    "Quinnipiac Bobcats":"Quinnipiac",
    "Queens University Royals":"Queens",
    "Purdue Fort Wayne Mastodons":"Purdue Fort Wayne",
    "Providence Friars":"Providence",
    "Princeton Tigers":"Princeton",
    "Presbyterian Blue Hose":"Presbyterian",
    "Prairie View A&M Panthers":"Prairie View A&M",
    "Portland State Vikings":"Portland St.",
    "Portland Pilots":"Portland",
    "Pittsburgh - Greensburg Bobcats":"Pittsburgh",
    "Pepperdine Waves":"Pepperdine",
    "Penn State-York Nittany Lions":"Penn",
    "Penn State-Shenango Nittany Lions":"Penn",
    "Penn State-New Kensington Lions":"Penn",
    "Penn State-Behrend Lions":"Penn",
    "Penn State Hazleton Nittany Lions":"Penn",
    "Penn State (Brandywine) Lions":"Penn",
    "Penn St Abington Nittany Lions":"Penn",
    "Pacific Union PACIFIC UNION":"Pacific",
    "Pacific Tigers":"Pacific",
    "Pacific Lutheran Lutes":"Pacific",
    "Oral Roberts Golden Eagles":"Oral Roberts",
    "Old Dominion Monarchs":"Old Dominion",
    "Oklahoma Christian OKLAHOMA CHRISTIAN":"Oklahoma",
    "Ohio Wesleyan Battling Bishops":"Ohio",
    "Ohio Christian Trailblazers":"Ohio",
    "Ohio Bobcats":"Ohio",
    "Oakland Golden Grizzlies":"Oakland",
    "Oakland City Mighty Oaks":"Oakland",
    "Notre Dame (MD) Gators":"Notre Dame",
    "Northwestern State Demons":"Northwestern St.",
    "Northwestern Oklahoma State Rangers":"Northwestern",
    "Northern Kentucky Norse":"Northern Kentucky",
    "Northern Iowa Panthers":"Northern Iowa",
    "Northern Illinois Huskies":"Northern Illinois",
    "Northern Colorado Bears":"Northern Colorado",
    "Northern Arizona Lumberjacks":"Northern Arizona",
    "Northeastern State RiverHawks":"Northeastern",
    "Northeastern Huskies":"Northeastern",
    "North Texas Mean Green":"North Texas",
    "North Florida Ospreys":"North Florida",
    "North Dakota State Bison":"North Dakota St.",
    "North Dakota Fighting Hawks":"North Dakota",
    "North Carolina Central Eagles":"North Carolina Central",
    "North Carolina A&T Aggies":"North Carolina A&T",
    "North Alabama Lions":"North Alabama",
    "Nicholls Colonels":"Nicholls",
    "Niagara Purple Eagles":"Niagara",
    "New Orleans Privateers":"New Orleans",
    "New Mexico State Aggies":"New Mexico St.",
    "New Mexico Highlands Cowboys":"New Mexico",
    "New Haven Chargers":"New Haven",
    "New Hampshire Wildcats":"New Hampshire",
    "Navy Midshipmen":"Navy",
    "NJIT Highlanders":"NJIT",
    "Mount St. Mary's Mountaineers":"Mount St. Mary's",
    "Montana Tech Orediggers":"Montana",
    "Montana State Bobcats":"Montana St.",
    "Montana Grizzlies":"Montana",
    "Monmouth Hawks":"Monmouth",
    "Missouri State Bears":"Missouri St.",
    "Missouri Southern State Lions":"Missouri",
    "Missouri Baptist Spartans":"Missouri",
    "Mississippi Valley State Delta Devils":"Mississippi Valley St.",
    "Mississippi University For Women Owls":"Mississippi",
    "Minnesota Crookston Golden Eagles":"Minnesota",
    "Milwaukee Panthers":"Milwaukee",
    "Middle Tennessee Blue Raiders":"Middle Tennessee",
    "Merrimack Warriors":"Merrimack",
    "Mercyhurst Lakers":"Mercyhurst",
    "Mercer Bears":"Mercer",
    "McNeese Cowboys":"McNeese",
    "Massachusetts Minutemen":"Massachusetts",
    "Maryland Eastern Shore Hawks":"Maryland Eastern Shore",
    "Marshall Thundering Herd":"Marshall",
    "Marist Red Foxes":"Marist",
    "Manhattan Jaspers":"Manhattan",
    "Manhattan Christian Thunder":"Manhattan",
    "Maine Black Bears":"Maine",
    "Loyola Marymount Lions":"Loyola Marymount",
    "Loyola Chicago Ramblers":"Loyola Chicago",
    "Louisiana Tech Bulldogs":"Louisiana Tech",
    "Louisiana Ragin' Cajuns":"Louisiana",
    "Louisiana Christian Wildcats":"Louisiana",
    "Longwood Lancers":"Longwood",
    "Little Rock Trojans":"Little Rock",
    "Lipscomb Bisons":"Lipscomb",
    "Lindenwood Lions":"Lindenwood",
    "Liberty Flames":"Liberty",
    "Lehigh Mountain Hawks":"Lehigh",
    "Le Moyne Dolphins":"Le Moyne",
    "Lamar Cardinals":"Lamar",
    "Lafayette Leopards":"Lafayette",
    "La Salle Explorers":"La Salle",
    "Kentucky State Thorobreds":"Kentucky",
    "Kentucky Christian Knights":"Kentucky",
    "Kansas City Roos":"Kansas City",
    "Kansas Christian Falcons":"Kansas",
    "James Madison Dukes":"James Madison",
    "Jacksonville State Gamecocks":"Jacksonville St.",
    "Jacksonville Dolphins":"Jacksonville",
    "Iona Gaels":"Iona",
    "Indiana University East IU EAST":"Indiana",
    "Indiana State Sycamores":"Indiana St.",
    "Incarnate Word Cardinals":"Incarnate Word",
    "Illinois Tech Scarlet Hawks":"Illinois",
    "Illinois State Redbirds":"Illinois St.",
    "Idaho Vandals":"Idaho",
    "Idaho State Bengals":"Idaho St.",
    "Howard Payne Yellow Jackets":"Howard",
    "Howard Bison":"Howard",
    "Houston Christian Huskies":"Houston Christian",
    "Holy Cross Crusaders":"Holy Cross",
    "Holy Cross College (IN) Saints":"Holy Cross",
    "Hofstra Pride":"Hofstra",
    "Harvard Crimson":"Harvard",
    "Hampton Pirates":"Hampton",
    "Green Bay Phoenix":"Green Bay",
    "Grand Canyon Lopes":"Grand Canyon",
    "Georgia State Panthers":"Georgia St.",
    "Georgia Southern Eagles":"Georgia Southern",
    "Georgia College Bobcats":"Georgia",
    "Georgetown Hoyas":"Georgetown",
    "George Mason Patriots":"George Mason",
    "Furman Paladins":"Furman",
    "Fordham Rams":"Fordham",
    "Florida National Conquistadors":"Florida",
    "Florida Memorial FLORIDA MEMORIAL":"Florida",
    "Florida International Panthers":"FIU",
    "Florida Gulf Coast Eagles":"Florida Gulf Coast",
    "Florida Atlantic Owls":"Florida Atlantic",
    "Florida A&M Rattlers":"Florida A&M",
    "Fairleigh Dickinson Knights":"Fairleigh Dickinson",
    "Fairfield Stags":"Fairfield",
    "Evansville Purple Aces":"Evansville",
    "Elon Phoenix":"Elon",
    "Eastern Washington Eagles":"Eastern Washington",
    "Eastern Michigan Eagles":"Eastern Michigan",
    "Eastern Kentucky Colonels":"Eastern Kentucky",
    "Eastern Illinois Panthers":"Eastern Illinois",
    "East Texas A&M Lions":"East Texas A&M",
    "East Carolina Pirates":"East Carolina",
    "Duquesne Dukes":"Duquesne",
    "Drexel Dragons":"Drexel",
    "Drake Bulldogs":"Drake",
    "Detroit Mercy Titans":"Detroit Mercy",
    "Denver Pioneers":"Denver",
    "Delaware State Hornets":"Delaware St.",
    "Delaware Blue Hens":"Delaware",
    "DePaul Blue Demons":"DePaul",
    "Davidson Wildcats":"Davidson",
    "Dartmouth Big Green":"Dartmouth",
    "Cornell Big Red":"Cornell",
    "Columbia Lions":"Columbia",
    "Columbia International Rams":"Columbia",
    "Columbia College (SC) Fighting Koalas":"Columbia",
    "Colorado College Tigers":"Colorado",
    "Colorado Christian Cougars":"Colorado",
    "Colgate Raiders":"Colgate",
    "Coastal Carolina Chanticleers":"Coastal Carolina",
    "Clemson Tigers":"Clemson",
    "Cincinnati Clermont Cougars":"Cincinnati",
    "Cincinnati Bearcats":"Cincinnati",
    "Chattanooga Mocs":"Chattanooga",
    "Charlotte 49ers":"Charlotte",
    "Charleston Southern Buccaneers":"Charleston Southern",
    "Charleston Cougars":"Charleston",
    "Central Michigan Chippewas":"Central Michigan",
    "Central Connecticut Blue Devils":"Central Connecticut",
    "Central Arkansas Bears":"Central Arkansas",
    "Canisius Golden Griffins":"Canisius",
    "Campbell Fighting Camels":"Campbell",
    "California Baptist Lancers":"Cal Baptist",
    "Cal Poly Mustangs":"Cal Poly",
    "Butler Bulldogs":"Butler",
    "Buffalo Bulls":"Buffalo",
    "Bucknell Bison":"Bucknell",
    "Bryant Str-Alb Bobcats":"Bryant",
    "Bryant Bulldogs":"Bryant",
    "Bryant & Stratton (Ohio) Bobcats":"Bryant",
    "Brown Bears":"Brown",
    "Bradley Braves":"Bradley",
    "Bowling Green Falcons":"Bowling Green",
    "Boston University Terriers":"Boston University",
    "Boston College Eagles":"Boston College",
    "Binghamton Bearcats":"Binghamton",
    "Belmont Bruins":"Belmont",
    "Belmont Abbey Crusaders":"Belmont",
    "Bellarmine Knights":"Bellarmine",
    "Austin Peay Governors":"Austin Peay",
    "Army Black Knights":"Army",
    "Arkansas Tech Wonder Boys":"Arkansas",
    "Arkansas State Red Wolves":"Arkansas St.",
    "Arkansas Baptist Buffaloes":"Arkansas",
    "American University Eagles":"American",
    "Alabama State Hornets":"Alabama St.",
    "Alabama A&M Bulldogs":"Alabama A&M",
    "Akron Zips":"Akron",
    "Air Force Falcons":"Air Force",
    "Abilene Christian Wildcats":"Abilene Christian",
    "Colorado Buffaloes":"Colorado",
    "Creighton Bluejays":"Creighton",
    "Nevada Wolf Pack":"Nevada",
    "Illinois St Redbirds":"Illinois St.",
    "Wichita St Shockers":"Wichita St.",
    "Tulsa Golden Hurricane":"Tulsa",
    "Dayton Flyers":"Dayton",
    "St. John's Red Storm":"St. John's",
    "Nebraska Cornhuskers":"Nebraska",
    "Appalachian State Mountaineers":"Appalachian St.",
    "Sam Houston Bearkats":"Sam Houston St.","Sam Houston State Bearkats":"Sam Houston St.",
}
def R(n): return XWALK.get(str(n).strip(), str(n).strip())

def nb_lpmf(k,mu,phi):
    r=1/phi; p=r/(r+mu)
    return (special.gammaln(k+r)-special.gammaln(r)-special.gammaln(k+1)
            +r*np.log(max(p,1e-12))+k*np.log(max(1-p,1e-12)))

def price_game(mp,h_ortg,a_ortg,sp,tot):
    pts,wts=np.polynomial.hermite.hermgauss(NQ)
    lmu=math.log(max(mp,1))-0.5*SIG*SIG
    g=np.zeros((MX+1,MX+1)); xs=np.arange(MX+1,dtype=float)
    eh=ea=eh2=ea2=eha=0.0; mha=np.zeros(MX+1); maa=np.zeros(MX+1)
    for pt,wt in zip(pts,wts):
        pace=math.exp(lmu+math.sqrt(2)*SIG*pt); wg=wt/math.sqrt(math.pi)
        mh=max(pace*h_ortg/100,0.1); ma=max(pace*a_ortg/100,0.1)
        ph=np.exp(nb_lpmf(xs,mh,PHI)); ph/=ph.sum()
        pa=np.exp(nb_lpmf(xs,ma,PHI)); pa/=pa.sum()
        g+=wg*np.outer(ph,pa); _eh=(xs*ph).sum(); _ea=(xs*pa).sum()
        eh+=wg*_eh; ea+=wg*_ea
        eh2+=wg*((xs**2)*ph).sum(); ea2+=wg*((xs**2)*pa).sum(); eha+=wg*_eh*_ea
        mha+=wg*ph; maa+=wg*pa
    s=g.sum()
    if s>0: g/=s; mha/=mha.sum(); maa/=maa.sum()
    vh=eh2-eh**2; va=ea2-ea**2; cov=eha-eh*ea
    n=g.shape[0]; mg=np.zeros(2*n-1); tg=np.zeros(2*n-1)
    mv=np.arange(-(n-1),n); tv=np.arange(2*n-1)
    for i in range(n):
        np.add.at(mg,i-np.arange(n)+n-1,g[i]); np.add.at(tg,i+np.arange(n),g[i])
    return {"eh":eh,"ea":ea,"gs":g.sum(),
            "sd_m":math.sqrt(max(vh+va-2*cov,0)),"sd_t":math.sqrt(max(vh+va+2*cov,0)),
            "corr":cov/math.sqrt(max(vh*va,1e-9)),
            "p_ml":float(mg[mv>0].sum()),
            "p_hc":float(mg[mv>-sp].sum()) if sp is not None else float("nan"),
            "p_ov":float(tg[tv>tot].sum()) if tot is not None else float("nan"),
            "p_h70":float(mha[70:].sum()),"p_h75":float(mha[75:].sum()),
            "p_a70":float(maa[70:].sum()),"p_a75":float(maa[75:].sum())}

def amer(p):
    if p is None or (isinstance(p,float) and math.isnan(p)): return float("nan")
    p=max(min(float(p),0.9999),0.0001)
    return round(-(p/(1-p))*100) if p>=0.5 else round(((1-p)/p)*100)

def load_slate(path,date_str):
    if not Path(path).exists(): log.error(f"Slate not found: {path}"); return pd.DataFrame()
    df=pd.read_csv(path); df.columns=[str(c).strip() for c in df.columns]
    log.info(f"  Raw columns: {list(df.columns)}")
    A={"Home Team":"HOME_KP","Away Team":"AWAY_KP","Site":"SITE",
       "Home spread line (input)":"mkt_spread","Game total line (input)":"mkt_total",
       "Cutoff":"DATE","HOME":"HOME_KP","AWAY":"AWAY_KP","site":"SITE",
       "SPREAD":"mkt_spread","TOTAL":"mkt_total","spread":"mkt_spread","total":"mkt_total",
       "CLOSING_SPREAD":"mkt_spread","CLOSING_TOTAL":"mkt_total","game_id":"GAME_ID","cutoff":"DATE"}
    df=df.rename(columns={k:v for k,v in A.items() if k in df.columns})
    if "HOME_KP" not in df.columns or "AWAY_KP" not in df.columns:
        log.error(f"Missing HOME_KP/AWAY_KP. Columns: {list(df.columns)}"); return pd.DataFrame()
    if "DATE" not in df.columns: df["DATE"]=date_str
    df["DATE"]=pd.to_datetime(df["DATE"],errors="coerce").fillna(pd.Timestamp(date_str))
    if "GAME_ID" not in df.columns: df["GAME_ID"]=[f"PROD_{date_str}_{i:03d}" for i in range(len(df))]
    if "SITE" not in df.columns: df["SITE"]="H"
    df["SITE"]=df["SITE"].astype(str).str.upper().map(
        {"H":"H","N":"N","HOME":"H","NEUTRAL":"N","ROAD":"H"}).fillna("H")
    mask=df["DATE"].dt.strftime("%Y-%m-%d")==date_str
    if mask.sum()<len(df): df=df[mask].reset_index(drop=True)
    df["HOME_KP"]=df["HOME_KP"].astype(str).str.strip().apply(R)
    df["AWAY_KP"]=df["AWAY_KP"].astype(str).str.strip().apply(R)
    df=df[df["HOME_KP"]!=""].reset_index(drop=True)
    log.info(f"  Slate {date_str}: {len(df)} games  {df['SITE'].value_counts().to_dict()}")
    return df

def team_state_asof(baselines_path,date_str):
    bas=pd.read_csv(baselines_path,parse_dates=["DATE"])
    asof=bas[bas["DATE"]<=pd.Timestamp(date_str)].copy()
    if len(asof)==0: log.error(f"No rows <= {date_str}"); return None
    idx=asof.groupby("KP_NAME")["DATE"].idxmax()
    ts=asof.loc[idx].set_index("KP_NAME")
    lg_sym=(asof["blend_OEFF"].mean()+asof["blend_DEFF"].mean())/2
    lg_tp=asof["blend_POSS"].mean()
    log.info(f"  Baselines as-of {date_str}: {len(asof)} rows  last={asof['DATE'].max().date()}  teams={len(ts)}")
    log.info(f"  BDB lg_sym={lg_sym:.3f}  BDB lg_tp={lg_tp:.3f}")
    return ts,lg_sym,lg_tp

def fit_sa(bp,date_str,kp,kp_lg_sym,kp_lg_tp,bdb_lg_sym,bdb_lg_tp,window=60):
    bas=pd.read_csv(bp,parse_dates=["DATE"])
    cutoff=pd.Timestamp(date_str); start=cutoff-pd.Timedelta(days=window)
    h=bas[(bas["DATE"]>=start)&(bas["DATE"]<cutoff)&(bas["VENUE"]=="Home")]
    a=bas[(bas["DATE"]>=start)&(bas["DATE"]<cutoff)&(bas["VENUE"]=="Road")]
    p=h.merge(a,on="GAME_ID",suffixes=("_h","_a")).dropna(subset=["F_h","F_a"])
    if len(p)<20: log.warning(f"  Only {len(p)} pairs — using 3.5"); return 3.5
    p["margin"]=p["F_h"]-p["F_a"]
    def loss(sa):
        err=[]
        for _,r in p.iterrows():
            hn=R(r.get("KP_NAME_h","")); an=R(r.get("KP_NAME_a",""))
            kh=hn in kp.index; ka=an in kp.index
            koe_h=float(kp.loc[hn,"AdjOE"]) if kh else kp_lg_sym
            kde_h=float(kp.loc[hn,"AdjDE"]) if kh else kp_lg_sym
            ktp_h=float(kp.loc[hn,"AdjTempo"]) if kh else kp_lg_tp
            koe_a=float(kp.loc[an,"AdjOE"]) if ka else kp_lg_sym
            kde_a=float(kp.loc[an,"AdjDE"]) if ka else kp_lg_sym
            ktp_a=float(kp.loc[an,"AdjTempo"]) if ka else kp_lg_tp
            bh=float(r.get("blend_OEFF_h",bdb_lg_sym)); bdh=float(r.get("blend_DEFF_h",bdb_lg_sym))
            ba=float(r.get("blend_OEFF_a",bdb_lg_sym)); bda=float(r.get("blend_DEFF_a",bdb_lg_sym))
            bth=float(r.get("blend_POSS_h",bdb_lg_tp)); bta=float(r.get("blend_POSS_a",bdb_lg_tp))
            oe_h=koe_h+LAM_OE*(bh-bdb_lg_sym); de_h=kde_h+LAM_DE*(bdh-bdb_lg_sym)
            oe_a=koe_a+LAM_OE*(ba-bdb_lg_sym); de_a=kde_a+LAM_DE*(bda-bdb_lg_sym)
            tp_h=ktp_h+LAM_TP*(bth-bdb_lg_tp); tp_a=ktp_a+LAM_TP*(bta-bdb_lg_tp)
            mp=0.85*(2/(1/max(tp_h,50)+1/max(tp_a,50)))+0.15*kp_lg_tp
            oh=kp_lg_sym+WO*(oe_h-kp_lg_sym)+WD*(de_a-kp_lg_sym)+sa
            oa=kp_lg_sym+WO*(oe_a-kp_lg_sym)+WD*(de_h-kp_lg_sym)-sa
            err.append(mp*(oh-oa)/100-float(r["margin"]))
        return float(np.mean(err)**2)
    res=optimize.minimize_scalar(loss,bounds=(0.5,7.0),method="bounded")
    log.info(f"  sa_fit={res.x:.3f} from {len(p)} H/R pairs (last {window}d)")
    return float(res.x)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slate",     default="cbb_cache/GameInputs.csv")
    ap.add_argument("--baselines", default="cbb_cache/TeamBaselines.csv")
    ap.add_argument("--kenpom",    default="cbb_cache/KenPom_Ratings_2026.csv")
    ap.add_argument("--kenpom-ff", default="cbb_cache/KenPom_FourFactors_2026.csv",dest="kenpom_ff")
    ap.add_argument("--output",    default="cbb_cache/MatchupLatents_today_teamonly.csv")
    ap.add_argument("--date",      default="2026-03-21")
    args=ap.parse_args()

    log.info("="*65)
    log.info("Phase 3A.1 — team_only_v1_p2_30")
    log.info(f"  Date={args.date}  phi={PHI}  sigma={SIG}")
    log.info(f"  Mean layer: P2_30  lam_oe={LAM_OE}  lam_de={LAM_DE}  lam_tp={LAM_TP}")
    log.info("="*65)

    slate=load_slate(args.slate,args.date)
    if len(slate)==0: sys.exit(1)

    obj=team_state_asof(args.baselines,args.date)
    if obj is None: sys.exit(1)
    ts,bdb_lg_sym,bdb_lg_tp=obj

    kp=pd.read_csv(args.kenpom); kp["TeamName"]=kp["TeamName"].str.strip(); kp=kp.set_index("TeamName")
    kp_lg_sym=(kp["AdjOE"].mean()+kp["AdjDE"].mean())/2; kp_lg_tp=kp["AdjTempo"].mean()
    log.info(f"  KenPom: {len(kp)} teams  kp_lg_sym={kp_lg_sym:.2f}  kp_lg_tp={kp_lg_tp:.2f}")

    sa_fit=fit_sa(args.baselines,args.date,kp,kp_lg_sym,kp_lg_tp,bdb_lg_sym,bdb_lg_tp)

    def gs(t,col,fb):
        if t in ts.index:
            v=ts.loc[t,col]; return float(v) if pd.notna(v) else fb
        return fb

    rows=[]; kp_both=0; kp_miss=[]
    for _,game in slate.iterrows():
        h=str(game["HOME_KP"]); a=str(game["AWAY_KP"])
        site=str(game.get("SITE","H")).upper()
        if site not in("H","N"): site="H"

        kh=h in kp.index; ka=a in kp.index
        if kh and ka: kp_both+=1
        else: kp_miss.append(f"{h}(kp={kh}) vs {a}(kp={ka})")

        kp_oe_h=float(kp.loc[h,"AdjOE"])    if kh else kp_lg_sym
        kp_de_h=float(kp.loc[h,"AdjDE"])    if kh else kp_lg_sym
        kp_tp_h=float(kp.loc[h,"AdjTempo"]) if kh else kp_lg_tp
        kp_oe_a=float(kp.loc[a,"AdjOE"])    if ka else kp_lg_sym
        kp_de_a=float(kp.loc[a,"AdjDE"])    if ka else kp_lg_sym
        kp_tp_a=float(kp.loc[a,"AdjTempo"]) if ka else kp_lg_tp

        bdb_oe_h=gs(h,"blend_OEFF",bdb_lg_sym); bdb_de_h=gs(h,"blend_DEFF",bdb_lg_sym); bdb_tp_h=gs(h,"blend_POSS",bdb_lg_tp)
        bdb_oe_a=gs(a,"blend_OEFF",bdb_lg_sym); bdb_de_a=gs(a,"blend_DEFF",bdb_lg_sym); bdb_tp_a=gs(a,"blend_POSS",bdb_lg_tp)
        h_gpd1=gs(h,"games_played",30); a_gpd1=gs(a,"games_played",30)
        h_qual=str(ts.loc[h,"data_quality"]) if h in ts.index else "NO_STATE"
        a_qual=str(ts.loc[a,"data_quality"]) if a in ts.index else "NO_STATE"

        oe_h=kp_oe_h+LAM_OE*(bdb_oe_h-bdb_lg_sym)
        de_h=kp_de_h+LAM_DE*(bdb_de_h-bdb_lg_sym)
        tp_h=kp_tp_h+LAM_TP*(bdb_tp_h-bdb_lg_tp)
        oe_a=kp_oe_a+LAM_OE*(bdb_oe_a-bdb_lg_sym)
        de_a=kp_de_a+LAM_DE*(bdb_de_a-bdb_lg_sym)
        tp_a=kp_tp_a+LAM_TP*(bdb_tp_a-bdb_lg_tp)
        blg=kp_lg_sym

        sa=sa_fit if site=="H" else 0.0
        harm=2/(1/max(tp_h,50)+1/max(tp_a,50)); mp=0.85*harm+0.15*kp_lg_tp
        h_ortg=blg+WO*(oe_h-blg)+WD*(de_a-blg)+sa
        a_ortg=blg+WO*(oe_a-blg)+WD*(de_h-blg)-sa

        sp_r=float(game.get("mkt_spread",float("nan")) or float("nan"))
        tt_r=float(game.get("mkt_total", float("nan")) or float("nan"))
        sp=sp_r if not math.isnan(sp_r) else None
        tt=tt_r if not math.isnan(tt_r) else None

        pmf=price_game(mp,h_ortg,a_ortg,sp,tt)
        if abs(pmf["gs"]-1)>1e-8:
            log.warning(f"  PMF gs={pmf['gs']:.8f} for {h} vs {a}"); continue

        rows.append({
            "GAME_ID":game.get("GAME_ID",f"PROD_{args.date}"),
            "DATE":args.date,"HOME_KP":h,"AWAY_KP":a,"SITE":site,
            "model_version":"team_only_v1_p2_30",
            "mean_layer":"KP_backbone_plus_BDB_lambda_0.30",
            "KP_AdjOE_h":round(kp_oe_h,3),"KP_AdjDE_h":round(kp_de_h,3),"KP_AdjTempo_h":round(kp_tp_h,3),
            "KP_AdjOE_a":round(kp_oe_a,3),"KP_AdjDE_a":round(kp_de_a,3),"KP_AdjTempo_a":round(kp_tp_a,3),
            "bdb_blend_OEFF_h":round(bdb_oe_h,3),"bdb_blend_DEFF_h":round(bdb_de_h,3),"bdb_blend_POSS_h":round(bdb_tp_h,3),
            "bdb_blend_OEFF_a":round(bdb_oe_a,3),"bdb_blend_DEFF_a":round(bdb_de_a,3),"bdb_blend_POSS_a":round(bdb_tp_a,3),
            "h_gpd1":int(h_gpd1),"a_gpd1":int(a_gpd1),
            "oe_h":round(oe_h,3),"de_h":round(de_h,3),"tp_h":round(tp_h,3),
            "oe_a":round(oe_a,3),"de_a":round(de_a,3),"tp_a":round(tp_a,3),
            "blend_lg":round(blg,3),"sa_used":round(sa,3),"mu_pace":round(mp,3),
            "h_ortg":round(h_ortg,3),"a_ortg":round(a_ortg,3),
            "mu_home":round(mp*h_ortg/100,3),"mu_away":round(mp*a_ortg/100,3),
            "fair_spread":round(pmf["eh"]-pmf["ea"],3),"fair_total":round(pmf["eh"]+pmf["ea"],3),
            "fair_home_team_total":round(pmf["eh"],3),"fair_away_team_total":round(pmf["ea"],3),
            "p_ml_home_raw":round(pmf["p_ml"],4),
            "p_home_cover_raw":round(pmf["p_hc"],4) if not math.isnan(pmf["p_hc"]) else float("nan"),
            "p_over_raw":round(pmf["p_ov"],4) if not math.isnan(pmf["p_ov"]) else float("nan"),
            "p_h_gt70":round(pmf["p_h70"],4),"p_h_gt75":round(pmf["p_h75"],4),
            "p_a_gt70":round(pmf["p_a70"],4),"p_a_gt75":round(pmf["p_a75"],4),
            "fair_ml_home_american":amer(pmf["p_ml"]),"fair_ml_away_american":amer(1-pmf["p_ml"]),
            "edge_spread_pts":round((pmf["eh"]-pmf["ea"])-(-sp_r),3) if not math.isnan(sp_r) else float("nan"),
            "edge_total_pts":round((pmf["eh"]+pmf["ea"])-tt_r,3) if not math.isnan(tt_r) else float("nan"),
            "pred_sd_margin":round(pmf["sd_m"],3),"pred_sd_total":round(pmf["sd_t"],3),
            "pred_corr_ha":round(pmf["corr"],4),
            "player_ortg_adj_h":0.0,"player_ortg_adj_a":0.0,
            "tempo_adj_h":0.0,"tempo_adj_a":0.0,
            "rotation_delta_h":0.0,"rotation_delta_a":0.0,
            "player_layer_applied":False,
            "kenpom_used":kh and ka,"kenpom_h_joined":kh,"kenpom_a_joined":ka,
            "h_data_quality":h_qual,"a_data_quality":a_qual,
            "pmf_grid_sum":round(pmf["gs"],10),
            "phi_used":PHI,"sigma_used":SIG,
            "lam_oe":LAM_OE,"lam_de":LAM_DE,"lam_tp":LAM_TP,
            "mkt_spread":sp_r,"mkt_total":tt_r,
        })

    result=pd.DataFrame(rows)
    if len(result)==0: log.error("No games scored."); sys.exit(1)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output,index=False)

    log.info(f"\n{'='*65}\nVERIFICATION SUMMARY (team_only_v1_p2_30)\n{'='*65}")
    log.info(f"  Scored:                      {len(result)}")
    log.info(f"  H/R: {(result['SITE']=='H').sum()}  Neutral: {(result['SITE']=='N').sum()}")
    log.info(f"  KenPom both joined:          {result['kenpom_used'].sum()} / {len(result)}")
    log.info(f"  BDB-only fallback:           {(~result['kenpom_used']).sum()}")
    if kp_miss: log.warning(f"  Misses: {kp_miss}")
    log.info(f"  player_layer_applied=False:  {(~result['player_layer_applied']).all()}")
    log.info(f"  model_version:               team_only_v1_p2_30")
    log.info(f"  PMF max grid_sum err:        {(result['pmf_grid_sum']-1).abs().max():.2e}")
    log.info(f"  Games w/ mkt_spread:         {result['mkt_spread'].notna().sum()}")
    log.info(f"  Games w/ mkt_total:          {result['mkt_total'].notna().sum()}")
    log.info(f"\n  DISTRIBUTIONS:")
    for col in ["fair_spread","fair_total","pred_sd_margin","pred_sd_total","pred_corr_ha"]:
        v=result[col].dropna().astype(float)
        log.info(f"    {col:<24}: mean={v.mean():+.3f}  SD={v.std():.3f}  min={v.min():+.3f}  max={v.max():+.3f}")
    if result["mkt_spread"].notna().sum()>3:
        both=result.dropna(subset=["fair_spread","mkt_spread"])
        c=float(np.corrcoef(both["fair_spread"],-both["mkt_spread"])[0,1])
        mad=float((both["fair_spread"]-(-both["mkt_spread"])).abs().mean())
        log.info(f"    corr(fair_spread,-mkt_spread): {c:.4f}  {'PASS' if c>=0.80 else 'CHECK'}")
        log.info(f"    MAD vs market:                 {mad:.3f} pts")
    log.info(f"\n  SAMPLE TRACES (first 5):")
    for _,r in result.head(5).iterrows():
        log.info(f"    [{r['HOME_KP']} vs {r['AWAY_KP']}] site={r['SITE']} kp={r['kenpom_used']}")
        log.info(f"      KP_OE_h={r['KP_AdjOE_h']:.2f} bdb_oe={r['bdb_blend_OEFF_h']:.2f} -> oe_h={r['oe_h']:.3f}")
        log.info(f"      KP_DE_h={r['KP_AdjDE_h']:.2f} bdb_de={r['bdb_blend_DEFF_h']:.2f} -> de_h={r['de_h']:.3f}")
        log.info(f"      h_ortg={r['h_ortg']:.3f}  a_ortg={r['a_ortg']:.3f}  pace={r['mu_pace']:.3f}  sa={r['sa_used']:.3f}")
        log.info(f"      spread={r['fair_spread']:+.3f}  total={r['fair_total']:.3f}  p_ml={r['p_ml_home_raw']:.4f}")
        log.info(f"      mkt_spread={r['mkt_spread']}  mkt_total={r['mkt_total']}  grid={r['pmf_grid_sum']:.8f}")
    log.info(f"\n  Written: {args.output}")
    log.info("  NEXT: python3 build_team_only_workbook_v1.py")

if __name__=="__main__": main()
