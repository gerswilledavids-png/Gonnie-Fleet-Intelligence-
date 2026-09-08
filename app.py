            )

            price = numeric_series(
                trips_df,
                "cost_per_liter"
            )

            fixed = numeric_series(
                trips_df,
                "fixed_cost"
            ).sum()

            variable = numeric_series(
                trips_df,
                "variable_cost"
            ).sum()

            fuel_cost = (
                fuel * price
            ).sum()

            if "net_profit" in trips_df.columns: