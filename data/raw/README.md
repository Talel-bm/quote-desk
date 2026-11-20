# Raw data

## commodity_prices_worldbank.csv

Real monthly average prices, November 2023 to October 2026, in nominal US dollars.

- `copper_usd_per_mt`, `aluminum_usd_per_mt`: US$ per metric ton.
- `iron_ore_usd_per_dmtu`: iron ore, CFR spot, US$ per dry metric ton unit. Used only to steer the synthetic electrical-steel series (the Pink Sheet has no electrical-steel price).

Source: World Bank, *Commodity Price Data (The Pink Sheet)*, "CMO Historical Data Monthly", sheet "Monthly Prices", edition updated November 3, 2026. https://www.worldbank.org/commodities

Regenerate with `uv run quote-desk fetch-commodities`.
