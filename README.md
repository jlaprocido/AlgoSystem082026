Outlined below is an algorthimic trading system with the goal of making a profit trading US equities / ETFs at a reasonable return while providing live metrics to an html dashboard and daily updates to investors. 

Plan
1. Create data pulling file that creates a pandas dataframe of a universe of stocks from strategy file. Take in Alpaca and yfinance
2. strategy file that runs backtest, outlines what to trade, presents backtesting results
3. orders file that files orders with Alpaca, saves record of those orders to .csv or other saving system
4. risk management file that limits portfolio to a maximum loss and drawdown before selling all stocks / stocks at loss
5. dashboard file that shows current results on html website, ytd, full year, and by stock comparison
6. notification file that sends messages to my phone with daily results

Extra
- is there a way to host this data in the cloud?
- can I personalize the dashboard per investor?
    - can I model in what it would look like for those investors given fees?