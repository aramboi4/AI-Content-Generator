# App screens for the ads

Phone scenes in the Saturday ad show one of these at random on the phone a person holds.

- `site/`: the logexpense.site landing page as a phone shows it. Each ad run takes fresh screenshots;
  these copies are used if the site can't be loaded. Refresh them with `python -m acg screens`.
- `app/`: screenshots from inside the app (signed in), added by hand. Crop off the phone's status bar and
  navigation buttons first, and hide any real names or amounts you don't want in a public ad.
