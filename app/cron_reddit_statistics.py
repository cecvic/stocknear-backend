import json
import re
import requests
import praw
from datetime import datetime, timedelta
from collections import defaultdict
import os
from dotenv import load_dotenv
import sqlite3
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# Download required NLTK data
nltk.download('vader_lexicon', quiet=True)

# Initialize the NLTK sentiment analyzer
sia = SentimentIntensityAnalyzer()

con = sqlite3.connect('stocks.db')

cursor = con.cursor()
cursor.execute("PRAGMA journal_mode = wal")
cursor.execute("SELECT DISTINCT symbol FROM stocks")
stock_symbols = [row[0] for row in cursor.fetchall()]

etf_con = sqlite3.connect('etf.db')
etf_cursor = etf_con.cursor()
etf_cursor.execute("PRAGMA journal_mode = wal")
etf_cursor.execute("SELECT DISTINCT symbol FROM etfs")
etf_symbols = [row[0] for row in etf_cursor.fetchall()]

con.close()
etf_con.close()

load_dotenv()
client_key = os.getenv('REDDIT_API_KEY')
client_secret = os.getenv('REDDIT_API_SECRET')
user_agent = os.getenv('REDDIT_USER_AGENT')

# Initialize Reddit instance
reddit = praw.Reddit(
    client_id=client_key,
    client_secret=client_secret,
    user_agent=user_agent
)

# Function to save data
def save_data(data, filename):
    with open(f'json/reddit-tracker/wallstreetbets/{filename}', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compute_daily_statistics(file_path):
    # Load the data from the JSON file
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Initialize a defaultdict to store daily statistics
    daily_stats = defaultdict(lambda: {
        'post_count': 0, 
        'total_comments': 0, 
        'ticker_mentions': defaultdict(lambda: {'total': 0, 'PUT': 0, 'CALL': 0, 'sentiment': []}),
        'unique_tickers': set()
    })
    
    # Compile regex patterns for finding tickers, PUT, and CALL
    ticker_pattern = re.compile(r'\$([A-Z]+)')
    put_pattern = re.compile(r'\b(PUT|PUTS)\b', re.IGNORECASE)
    call_pattern = re.compile(r'\b(CALL|CALLS)\b', re.IGNORECASE)
    
    # Process each post
    for post in data:
        # Convert UTC timestamp to datetime object
        post_date = datetime.utcfromtimestamp(post['created_utc']).date()
        
        # Update statistics for this day
        daily_stats[post_date]['post_count'] += 1
        daily_stats[post_date]['total_comments'] += post['num_comments']
        
        # Find ticker mentions in title and selftext
        text_to_search = post['title'] + ' ' + post['selftext']
        tickers = ticker_pattern.findall(text_to_search)
        
        # Check for PUT and CALL mentions
        put_mentions = len(put_pattern.findall(text_to_search))
        call_mentions = len(call_pattern.findall(text_to_search))
        
        # Perform sentiment analysis
        sentiment_scores = sia.polarity_scores(text_to_search)
        
        for ticker in tickers:
            daily_stats[post_date]['ticker_mentions'][ticker]['total'] += 1
            daily_stats[post_date]['unique_tickers'].add(ticker)
            
            # Add PUT and CALL counts
            daily_stats[post_date]['ticker_mentions'][ticker]['PUT'] += put_mentions
            daily_stats[post_date]['ticker_mentions'][ticker]['CALL'] += call_mentions
            
            # Add sentiment score
            daily_stats[post_date]['ticker_mentions'][ticker]['sentiment'].append(sentiment_scores['compound'])
    
    # Calculate averages and format the results
    formatted_stats = []
    for date, stats in sorted(daily_stats.items(), reverse=True):
        formatted_stats.append({
            'date': date.isoformat(),
            'totalPosts': stats['post_count'],
            'totalComments': stats['total_comments'],
            'totalMentions': sum(mentions['total'] for mentions in stats['ticker_mentions'].values()),
            'companySpread': len(stats['unique_tickers']),
            'tickerMentions': [
                {
                    'symbol': ticker,
                    'count': mentions['total'],
                    'put': mentions['PUT'],
                    'call': mentions['CALL']
                }
                for ticker, mentions in stats['ticker_mentions'].items()
            ]
        })
    
    return formatted_stats, daily_stats

def compute_trending_tickers(daily_stats):
    today = datetime.now().date()
    seven_days_ago = today - timedelta(days=14)
    
    trending = defaultdict(lambda: {'total': 0, 'PUT': 0, 'CALL': 0, 'sentiment': []})
    
    for date, stats in daily_stats.items():
        if seven_days_ago <= date <= today:
            for ticker, counts in stats['ticker_mentions'].items():
                trending[ticker]['total'] += counts['total']
                trending[ticker]['PUT'] += counts['PUT']
                trending[ticker]['CALL'] += counts['CALL']
                trending[ticker]['sentiment'].extend(counts['sentiment'])
    
    trending_list = [
        {
            'symbol': symbol,
            'count': counts['total'],
            'put': counts['PUT'],
            'call': counts['CALL'],
            'avgSentiment': sum(counts['sentiment']) / len(counts['sentiment']) if counts['sentiment'] else 0
        }
        for symbol, counts in trending.items()
    ]
    trending_list.sort(key=lambda x: x['count'], reverse=True)

    for item in trending_list:
        symbol = item['symbol']
        if symbol in stock_symbols:
            item['assetType'] = 'stocks'
        elif symbol in etf_symbols:
            item['assetType'] = 'etf'
        else:
            item['assetType'] = ''
    
    return trending_list

# Usage
file_path = 'json/reddit-tracker/wallstreetbets/data.json'
daily_statistics, daily_stats_dict = compute_daily_statistics(file_path)
save_data(daily_statistics, 'stats.json')

# Compute and save trending tickers
trending_tickers = compute_trending_tickers(daily_stats_dict)
save_data(trending_tickers, 'trending.json')