# Storefront

Hey - if you're reading this, I'm probably already gone. I was the only
one working on this for the last year or so, sorry there isn't more
documentation than this. Should be everything you need to get it running
and find your way around, though. Ping me on LinkedIn if you're really
stuck, I guess.

## Running it

You need Docker. That's it.

```
docker compose up --build
```

First run will take a minute while Postgres initializes and Django runs
migrations. Once it's up, the site is on `http://localhost:8000`.

There's no data in a fresh database, so you'll want to seed it:

```
docker compose exec web python manage.py seed_data
```

That gives you a realistic-sized catalog, a couple hundred thousand
historical orders, and a pile of test users. Every seeded user has the
password `password123` (including `admin`, which also has staff/admin
access at `/admin/`). Don't use that account for anything real, it's
seed data.

If you want to poke around the database directly, `docker compose exec
db psql -U storefront storefront` gets you a `psql` shell.

## What this is

It's a fairly standard online store. The domain apps:

- **catalog** - products and categories. Product images live under
  `/app/media/products/`.
- **cart** - what's in someone's basket before they check out.
- **orders** - the order itself, its line items, and a rolling daily
  sales snapshot table used by the reporting page.
- **payments** - payment records tied 1:1 to an order. We don't
  actually talk to a real payment processor - `payments/services.py`
  simulates a charge and always approves it. Fine for now.
- **accounts** - user profiles (shipping details, phone number) on top
  of the built-in Django user model.
- **reports** - the sales dashboard at `/reports/sales/`. Renders a
  chart from the full order history. It's a lot of data so give it a
  few seconds to load.

Checkout is one atomic transaction - it locks the relevant product rows,
decrements stock, writes the order, its line items, and the payment
record all together. If anything in that chain fails, the whole order
rolls back and no stock is lost. This was a deliberate design decision
early on and it's worked well - never had a support ticket about
double-charged or phantom orders.

Every completed order also gets appended to `/app/logs/orders.log` as a
plain line, mostly so finance can grep it when they don't want to bug
me for a report.

There are two background jobs that just run inside the app itself - one
tidies up carts nobody's touched in half an hour and puts the stock
back, the other recomputes the sales snapshot table every 15 minutes so
the reports page has something fresh to work from without redoing the
whole aggregation constantly. Logs for those go to
`/app/logs/scheduler.log` if you want to see them firing.

## Seeding data

`python manage.py seed_data` is idempotent - if you run it twice it
just notices the data's already there and skips ahead, so don't worry
about running it by accident. It generates:

- 20,000 users
- 200 categories, 50,000 products (with generated placeholder images)
- 200,000 orders across the last two years, with a realistic mix of
  statuses (most things end up delivered, some cancelled/refunded)
- ~600,000 order line items and matching payment records

Takes a couple of minutes. Grab a coffee.

## Creating an admin user

The seed command already creates one (`admin` / `password123`), so you
probably don't need to make another one. If you do:

```
docker compose exec web python manage.py createsuperuser
```

Admin site is at `/admin/`.

## Configuration

Nothing to configure - it's all in `config/settings.py`. Database
credentials, the Django secret key, everything. I know a lot of
tutorials tell you to pull that stuff from environment variables but
for a project this size it never seemed worth the extra layer of
indirection. It's all in one place if you ever need to change it.

## Load testing / smoke testing

There's a `loadtest/` folder with a few k6 scripts if you want to poke
at it under load:

- `browse.js` - just hits the catalog pages over and over.
- `checkout.js` - logs in as a random seeded user and runs a full
  add-to-cart-and-buy flow.
- `report.js` - repeatedly loads the sales dashboard.
- `session-integrity.js` - logs in, adds something to the cart, then
  checks back on it every couple of seconds for a few minutes to make
  sure it's still there.

Run any of them with `k6 run loadtest/<script>.js`. Pass
`-e BASE_URL=http://localhost:8000` if you're not running against the
default compose setup.

## Known issues

Nothing major, just some cosmetic stuff I never got around to:

- The category name generator occasionally produces slightly silly
  category names in seed data ("Purple Bicycle", that kind of thing).
  Harmless, just funny to scroll past in the admin.
- The order confirmation page doesn't show a nicely formatted date, just
  whatever Django's default datetime rendering gives you.
- Product search is a plain `icontains` on the name field, so it won't
  find things by description or category. Was on the list to improve,
  never got to it.
- The "related products" list on a product page is just "other things
  in the same category," not anything smarter. It's fine.
- Product images don't have alt text, so screen readers just announce
  the filename. Should fix at some point.
- The admin site shows all timestamps in UTC regardless of your
  browser's timezone. A little annoying if you're used to local time,
  but consistent at least.
- Catalog pagination is slightly off on the very last page for some
  category filters - you might see a shorter last page than expected.
  Doesn't drop any products, just cosmetic.

That's genuinely it. Good luck.
