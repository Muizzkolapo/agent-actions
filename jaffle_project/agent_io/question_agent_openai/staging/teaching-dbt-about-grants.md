
New in Core: easier access management with grants \| dbt Labs[Get an early peek at the first round of sessions at Coalesce 2024 in Las Vegas!](https://coalesce.getdbt.com/agenda)[On\-demand: Boost AI Reliability with dbt Cloud](https://www.getdbt.com/resources/webinars/boost-ai-reliability-with-dbt-cloud)[New release: Introducing dbt for Snowflake \- read more](https://www.getdbt.com/blog/introducing-dbt-for-snowflake)[Live event: Streamlining KPI Dashboards with the dbt Semantic Layer](https://www.getdbt.com/resources/webinars/dbt-labs-on-dbt-streamlining-kpi-dashboards-with-the-dbt-semantic-layer)[Join us for our next Semantic Layer workshop!](https://www.getdbt.com/resources/webinars/getting-started-with-the-dbt-semantic-layer)[Learn with us at our bi\-weekly demos and see dbt Cloud in action!](https://www.getdbt.com/resources/dbt-cloud-demos-with-experts)[Achieve a 194% ROI with dbt Cloud \| Read the study now!](https://www.getdbt.com/resources/study-forrester-tei-webinar/?utm_medium=social&utm_source=linkedin&utm_campaign=q3-2024_forrester-report-webinar_aw&utm_content=____&utm_term=all___)[Login](https://cloud.getdbt.com/)[![dbt](/_next/image?url=%2Fimg%2Flogos%2Fdbt-logo.svg&w=256&q=75)](/)Open menu[Blog](/blog) New in Core: easier access management with grants# New in Core: easier access management with grants

[![](/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Fwl0ndo6t%2Fmain%2F9b6517ce168315f8b005e5864bfb09f79416b7ca-256x256.jpg%3Ffit%3Dmax%26auto%3Dformat&w=640&q=75)](/authors/jeremy-cohen)[Jeremy Cohen](/authors/jeremy-cohen)Jul 25, 2022

[Product News](/blog/category/product-news)![](/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Fwl0ndo6t%2Fmain%2F4d3539d40ae7e96ed5655d3860e22510fcb32a64-2560x1440.jpg%3Ffit%3Dmax%26auto%3Dformat&w=3840&q=75)Hi all, Jeremy (Jerco) here.

Did you see [my roadmap post](https://github.com/dbt-labs/dbt-core/blob/main/docs/roadmap/2022-05-dbt-a-core-story.md "my roadmap post") back in May? I’ll be writing an update for that soon, as we gear up for some [big new functionality](https://github.com/dbt-labs/dbt-core/discussions/5261 "big new functionality") coming in v1\.3 ("large subject in ophiology," six letters). For now, I want to cue you in on a cool thing that we just shipped, which might have been easy to miss amidst the other headlines.

We just released dbt Core v1\.2, keeping with our [regular 3\-month cadence for new minor version releases](https://docs.getdbt.com/docs/core-versions#future-versions "regular 3-month cadence for new minor version releases"). The focus in v1\.2 was on ergonomics for adapters and materializations. This is code that you, as an end user, may never touch — but you definitely feel its effects, every time you run a dbt model that does what it’s supposed to, or get to install a dbt package that “just works” on your database.

There’s some code that you *have* been writing, however, directly and yourself — code that we wanted to make a more seamless part of the dbt experience. I’m talking about **grants**.

## Why grants?

Why grant access at all? Why not just keep all your dbt models to yourself?

The whole point of having a dbt project is to produce datasets that you ultimately want to share with others. For starters, it’s easy enough to share the outputs of *every* model with *every* database user. Over time, though, as your team grows and your project scales up, this practice doesn’t last\*.\*

Why not? It could be the nature of the data\*—\*sensitive information, which should remain on a need\-to\-see basis—or the nature of your [DAG](https://docs.getdbt.com/terms/dag "DAG"). To rein in complexity and avoid duplicated logic, you’re likely to build out [intermediate transformations](https://docs.getdbt.com/guides/best-practices/how-we-structure/3-intermediate "intermediate transformations"): modular molecules that are essential for you and fellow dbt developers, but hardly ready for external consumption. You don’t want the unpleasant surprise of finding that `int_payments_pivoted_to_orders` is now an essential input for someone else’s dashboard!

If you’ve been using dbt for a while, this should sound familiar. We’ve long encouraged you to put your models in clearly named databases and schemas (never `public` !). We’ve implored you to organize them into domains by subfolder, and configure sensible defaults for all models in those groups—all doable with just a few lines in `dbt_project.yml` . And we’ve encouraged you to do something similar with `grants` , leveraging built\-in database permissions to ensure that the right people have access to the right tables and views.

Nice and simple... and yet it still took [thousands of words](https://discourse.getdbt.com/t/the-exact-grant-statements-we-use-in-a-dbt-project/430 "thousands of words") to step through the many available options and trade\-offs. It’s an excellent post, one that has stood the test of time, and remained our go\-to link through the years—but no longer. In v1\.2, we've made an easy thing easy. We’ve made grants simple to configure, just the same way you’d configure `tags` or `schema` , and cued them up to run within standard materializations.

Post hooks, the mechanism we previously recommended, still serve a purpose, but I believe it’s a subtly different one. Custom hooks should be a way to *make a hard thing possible*, not the stuff that everyone needs right out of the box.

If you’re a person who writes dbt code, I recommend checking out [Doug’s DevHub post](https://docs.getdbt.com/blog/configuring-grants "Doug’s DevHub post"), which walks you through the specifics of *how* and *why* you’d want to implement the new feature.

### Is dbt a permission management system now?

Yes... to some extent.

We don't intend to build a full\-fledged permissioning system for your database — instantiating new users, creating new roles, associating new users with the appropriate roles.

But you can *already* use dbt today to:

* Create tables and views in your warehouse
* Capture metadata on those objects
* Query that metadata to understand how those objects are used downstream

It feels appropriate to add a 4th role (hah) to that scope:

* Manage other roles (people, tools, services) that get to interact with your dbt models

For folks who are happily using tools like Terraform to bootstrap their warehouse setup, and automate the application of permissions — great! dbt will continue to work for you, just as it has before. But we don’t think you should *need* to spin up another tool, no matter how good, just to manage something basic and intrinsic to dbt: who gets to use your model, as soon as it’s finished building.

### Grants schmants… I had a macro for that already!

“Teaching dbt about database permissions,” you say. “Why not try for some of the really fancy stuff?” Maybe you’ve got real use cases for features like:

* secure and authorized views
* row\-level and column\-level security policies
* cross\-account data shares

These are exciting features, and I could imagine someday building support for them into dbt\-core or specific database adapters. If dbt made it easy and simple to use these—say, a few lines of config—I’m sure it would tip the balance for many folks, who are wondering today if they have a use case that justifies a heavier lift with custom code.

Back in January, I had the chance to talk with many users about their unmet needs in dbt: things they felt were missing, new constructs we needed to add. Multiple folks told me that the code they had written for grants—code *already* in their project—was some of the gnarliest. It was tricky to debug, to test, to reason about, and to explain to colleagues. Even if tided up into macros, those same macros were now duplicated across hundreds, if not thousands of projects. In aggregate, that’s far from [DRY](https://docs.getdbt.com/terms/dry "DRY"). It became clear to me that this is one thing we’ve overlooked for a long time—a thing that’s been, in Tristan’s words, [“super\-budget literally forever.”](https://roundup.getdbt.com/p/the-response-you-deserve?s=r#:~:text=super%2Dbudget%20literally%20forever "“super-budget literally forever.”")

This is the nature of building a solid framework. We have to build the right foundations and abstractions for the things that feel obvious, before we can build support for the really cool next\-level capabilities. When we get there, we’ll know that we’re doing it on top of solid foundations.

You may get there before us! Compared to all the amazing stuff that community members are working on and experimenting with, the work of Core can feel slow\-going. But it’s our job to provide the standard framework—the core functionalities, well\-documented and rock\-solid for every use case, with graceful handling for known edge cases. Plus, testing—tons and tons of testing.

This is what we’re building, and will continue to build: A framework that gives you more things “for free,” so you can devote your time and attention to writing the code that *you* need, and writing it with leverage.

Last modified on: Jun 03, 2024

![](/_next/image?url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Fwl0ndo6t%2Fmain%2Fffd8a2782be2395ac0de21c38affcd431d86586a-1964x450.png%3Ffit%3Dmax%26auto%3Dformat&w=3840&q=75) Accelerate speed to insight   Democratize data responsibly   Build trust in data across business [Book a demo](/contact)**Achieve a 194% ROI with dbt Cloud. Access the Total Economic Impact™️ study to learn how. [Download now ›](https://www.getdbt.com/resources/study-forrester-tei/ "Download now ›")**

## Recent Posts





## Link
https://www.getdbt.com/blog/teaching-dbt-about-grants