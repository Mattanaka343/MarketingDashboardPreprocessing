from extract import linkedInExtraction,xExtraction
from transform import transform_metrics, transform_posts
from load import get_conn, pass_to_sql
from utils import find_files, send_mail, clear_temp_files

exceptions = []

big_m = ''

BRANDS = [('nurvai','Nurvai'),('business','Wexpand'),('talent','Wexpand Talent')]

engine = get_conn()
delete_files = True
message = 'Load succesful'

try:

    posts_dfs = []
    metrics_dfs = []

    paths = find_files()

    if paths is None:
        big_m = 'No files found for the ETL'
        raise FileNotFoundError
    
    for brand in BRANDS:
        m=''
        try:
            MetDF, PostDF = linkedInExtraction(paths,brand,engine)
            XMetDF, XPostDF = xExtraction(paths,brand,engine)

            metrics_dfs.append(MetDF)
            metrics_dfs.append(XMetDF)
            posts_dfs.append(PostDF)
            posts_dfs.append(XPostDF)            

            if MetDF is None and PostDF is not None:
                m = f"No Metrics Data found for {brand[1]}'s LinkedIN"
                raise FileNotFoundError
            
            elif MetDF is not None and PostDF is None:
                m = f"No Posts Data found for {brand[1]}'s LinkedIN"
                raise FileNotFoundError
            
            elif MetDF is None and PostDF is None:
                m = f"No Data found for {brand[1]}'s LinkedIN"
                raise FileNotFoundError
        except Exception as e:
            text = f'{type(e).__name__}: {str(e)} {m}'
            exceptions.append(text)
            continue

    no_mets = True
    no_posts = True
    small_m = ''

    try: 
        if all(df is None for df in metrics_dfs) or metrics_dfs == []:
            small_m = 'No Files For Metrics Found' 
            raise FileNotFoundError
        
        else: 
            no_mets = False
    
    except Exception as e:
        text = f'{type(e).__name__}: {str(e)} {small_m}'
        exceptions.append(text)
    
    try:
        if all(df is None for df in posts_dfs) or posts_dfs == []:
            small_m = 'No Files For Posts Found'
            raise FileNotFoundError

        else:
            no_posts = False

    except Exception as e:
        text = f'{type(e).__name__}: {str(e)} {small_m}'

    if no_mets and no_posts:
        big_m = 'Files Were Provided But Were Incomplete or Mistaken'
        raise FileNotFoundError
    
    if not(no_mets):
        dfs = []
        for df in metrics_dfs:
            if df is not None:
                dfs.append(df)
        
        MetricsDF = transform_metrics(dfs,engine)

        try:
            pass_to_sql(MetricsDF,'Metrics',engine)
        except Exception as e:
            delete_files = False
            text = f'{type(e).__name__}: {str(e)}'
            exceptions.append(text)
        

    if not(no_posts):
        dfs = []
        for df in posts_dfs:
            if df is not None:
                dfs.append(df)
        
        PostsDF, TermsDF, exceps = transform_posts(dfs,engine)

        if exceps != []:
            for excep in exceps:
                exceptions.append(excep)

        try:
            pass_to_sql(PostsDF,'Posts',engine)
        except Exception as e:
            delete_files = False
            text = f'{type(e).__name__}: {e}'
            exceptions.append(text)
        
        try:
            pass_to_sql(TermsDF,'Terms',engine)
        except Exception as e:
            delete_files = False
            text = f'{type(e).__name__}: {e}'
            exceptions.append(text)

except Exception as e:
    text = f'{type(e).__name__}: {str(e)} {big_m}'
    exceptions.append(text)

if delete_files and paths is not None:
    clear_temp_files(paths)


if exceptions != []:
    message = 'Exceptions were encountered while loading. The exceptions ecountered were the following: \n'
    exceptions = '\n'.join(exceptions)
    message += exceptions

send_mail('File Load Completion Status',message)
