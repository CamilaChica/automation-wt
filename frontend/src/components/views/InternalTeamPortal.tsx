import React, { useEffect, useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Gauge,
  HeartHandshake,
  Menu,
  PackageCheck,
  Plane,
  ShieldCheck,
  Sparkles,
  UsersRound,
  X,
} from 'lucide-react';
import './InternalTeamPortal.css';

const navigation = [
  { label: 'Our mission', href: '#mission' },
  { label: 'Operations', href: '#operations' },
  { label: 'Sales', href: '#sales' },
  { label: 'How we work', href: '#standards' },
];

const principles = [
  {
    number: '01',
    title: 'Respond with urgency',
    description: 'A grounded aircraft is a real disruption for the people waiting to get somewhere. We move every request with focus.',
    icon: Gauge,
  },
  {
    number: '02',
    title: 'Lead with human judgment',
    description: 'Automation gives us room to think. People own the high-stakes decisions, exceptions and relationships.',
    icon: HeartHandshake,
  },
  {
    number: '03',
    title: 'Close every loop',
    description: 'Clear handoffs, thoughtful follow-through and a record people can trust keep the whole operation moving.',
    icon: PackageCheck,
  },
];

export const InternalTeamPortal: React.FC = () => {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    document.title = 'Winged Tycoons | Internal Team Portal';
    const robots = document.createElement('meta');
    robots.name = 'robots';
    robots.content = 'noindex, nofollow';
    document.head.appendChild(robots);
    const elements = document.querySelectorAll<HTMLElement>('.wt-team-reveal');
    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );

    elements.forEach(element => observer.observe(element));
    return () => {
      observer.disconnect();
      robots.remove();
    };
  }, []);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className="wt-team-portal">
      <a className="wt-team-skip" href="#team-main">Skip to content</a>
      <header className="wt-team-header">
        <div className="wt-team-header-inner">
          <a className="wt-team-brand" href="#top" aria-label="Winged Tycoons team portal home" onClick={closeMenu}>
            <img src="/branding/WingedTycoons.png" alt="" width="58" height="44" />
            <span className="wt-team-brand-copy">
              <strong>WINGED TYCOONS</strong>
              <span>INTERNAL · PEOPLE IN MOTION</span>
            </span>
          </a>

          <button
            className="wt-team-menu-toggle"
            type="button"
            aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={menuOpen}
            aria-controls="team-navigation"
            onClick={() => setMenuOpen(open => !open)}
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>

          <nav
            id="team-navigation"
            className={`wt-team-nav${menuOpen ? ' is-open' : ''}`}
            aria-label="Team portal navigation"
          >
            {navigation.map(item => (
              <a key={item.href} href={item.href} onClick={closeMenu}>{item.label}</a>
            ))}
          </nav>

          <a className="wt-team-access" href="/internal">
            <ShieldCheck size={15} aria-hidden="true" />
            <span>Crew login</span>
            <ArrowUpRight size={15} aria-hidden="true" />
          </a>
        </div>
      </header>

      <main id="team-main">
        <section className="wt-team-hero" id="top" aria-labelledby="team-hero-heading">
          <div className="wt-team-hero-grid" aria-hidden="true" />
          <div className="wt-team-orbit wt-team-orbit-one" aria-hidden="true" />
          <div className="wt-team-orbit wt-team-orbit-two" aria-hidden="true" />
          <div className="wt-team-hero-inner">
            <div className="wt-team-hero-copy">
              <div className="wt-team-eyebrow"><span className="wt-team-live-dot" /> OPERATIONS × SALES · EVERYDAY HEROES</div>
              <h1 id="team-hero-heading">
                Every flight has
                <span>a team behind it.</span>
              </h1>
              <p className="wt-team-hero-lede">
                We are the people who turn a grounded aircraft into a plan, a plan into a promise, and a promise into a safe journey home. Operations and Sales—one crew, lifting every flight together.
              </p>
              <div className="wt-team-hero-actions">
                <a className="wt-team-button wt-team-button-primary" href="/internal">
                  Enter the team workspace <ArrowRight size={17} aria-hidden="true" />
                </a>
                <a className="wt-team-text-link" href="#mission">
                  The mission behind the work <ArrowDown size={15} aria-hidden="true" />
                </a>
              </div>
              <div className="wt-team-proof">
                <span><Check size={15} aria-hidden="true" /> Real people. Real impact.</span>
                <span><Check size={15} aria-hidden="true" /> One crew, all in.</span>
              </div>
            </div>

            <div className="wt-team-hero-visual">
              <img
                className="wt-team-hero-image"
                src="/team-collaboration.jpg"
                alt="A diverse group of teammates huddle around a table and stack their hands together"
              />
              <div className="wt-team-image-shade" aria-hidden="true" />
              <div className="wt-team-image-coordinate"><span className="wt-team-live-dot" /> ONE TEAM. ALL HEART.</div>
              <div className="wt-team-image-index">WT / CREW 01</div>
              <article className="wt-team-field-note">
                <div className="wt-team-field-note-top"><span>THIS IS OUR SUPERPOWER</span><Plane size={16} aria-hidden="true" /></div>
                <p>Show up for each other. Go the extra mile. Get the whole crew home.</p>
                <span className="wt-team-field-note-caption">BETTER, FASTER, TOGETHER</span>
              </article>
              <div className="wt-team-visual-corner"><UsersRound size={17} aria-hidden="true" /><span>ONE CREW, WORLDWIDE</span></div>
            </div>
          </div>
          <a className="wt-team-scroll-cue" href="#mission" aria-label="Scroll to our mission"><span /> SCROLL TO OUR MISSION</a>
          <span className="wt-team-hero-index" aria-hidden="true">01 — 03</span>
        </section>

        <section className="wt-team-signal-strip" aria-label="The people and purpose behind our work">
          <div className="wt-team-signal-inner">
            <div><span>THE SQUAD</span><strong>OPERATIONS + SALES</strong></div>
            <div><span>OUR SUPERPOWER</span><strong>WE SHOW UP FOR EACH OTHER</strong></div>
            <div><span>THE BIG PICTURE</span><strong>KEEP THE WORLD MOVING</strong></div>
          </div>
        </section>

        <section className="wt-team-mission wt-team-section" id="mission" aria-labelledby="team-mission-heading">
          <div className="wt-team-mission-copy wt-team-reveal">
            <span className="wt-team-eyebrow wt-team-eyebrow-dark"><span>01</span> / WHY WE FLY</span>
            <h2 id="team-mission-heading">A part number is never <em>just a part number.</em></h2>
            <p>
              Behind every request is a maintenance crew solving a hard problem, a traveler trying to make it home, and families and communities connected by the next flight. Our work helps aircraft return to service and supply chains keep their promise.
            </p>
            <p>
              We bring research, sourcing and thoughtful communication together so the right part can reach the right aircraft sooner. Technology helps us build momentum; our people make that momentum dependable.
            </p>
            <a className="wt-team-inline-link" href="#standards">What our standard looks like <ChevronRight size={17} aria-hidden="true" /></a>
          </div>
          <div className="wt-team-mission-card wt-team-reveal">
            <div className="wt-team-mission-card-mark"><Sparkles size={19} aria-hidden="true" /></div>
            <span>OUR NORTH STAR</span>
            <p>Be the crew people can count on. Move the right part, to the right plane, with a little more heart in every handoff.</p>
            <div className="wt-team-mission-card-foot"><span>THE POWER OF US</span><span>WT / 01</span></div>
          </div>
        </section>

        <section className="wt-team-functions" aria-label="How our teams move the mission forward">
          <article className="wt-team-function wt-team-operations wt-team-reveal" id="operations">
            <figure className="wt-team-function-photo">
              <img src="/operations-team.jpg" alt="Operations professional reviews a clipboard, ready to coordinate the next move" loading="lazy" />
              <figcaption><Gauge size={13} aria-hidden="true" /> READY FOR THE NEXT MOVE</figcaption>
            </figure>
            <span className="wt-team-function-number">02 / OPERATIONS</span>
            <div className="wt-team-function-icon"><Gauge size={21} aria-hidden="true" /></div>
            <h2>When it matters, we’re there.</h2>
            <p>Cool heads, kind hearts, quick moves. You bring the care and judgment that turn urgent requests into the right next step.</p>
            <a href="/internal">Go to the operations workspace <ArrowUpRight size={15} aria-hidden="true" /></a>
          </article>
          <article className="wt-team-function wt-team-sales wt-team-reveal" id="sales">
            <figure className="wt-team-function-photo">
              <img src="/sales-team.jpg" alt="Three colleagues work together reviewing documents and charts at a desk" loading="lazy" />
              <figcaption><HeartHandshake size={13} aria-hidden="true" /> LISTEN WELL. MOVE TOGETHER.</figcaption>
            </figure>
            <span className="wt-team-function-number">03 / SALES</span>
            <div className="wt-team-function-icon"><UsersRound size={21} aria-hidden="true" /></div>
            <h2>We make every promise personal.</h2>
            <p>You listen, connect the dots and build trust that lasts. Every conversation gets our customers closer to the people and parts they need.</p>
            <a href="/internal">Go to the sales workspace <ArrowUpRight size={15} aria-hidden="true" /></a>
          </article>
        </section>

        <section className="wt-team-standards wt-team-section" id="standards" aria-labelledby="team-standards-heading">
          <div className="wt-team-standards-heading wt-team-reveal">
            <div>
              <span className="wt-team-eyebrow wt-team-eyebrow-dark"><span>04</span> / HOW WE WIN TOGETHER</span>
              <h2 id="team-standards-heading">Be each other’s<br /><em>unfair advantage.</em></h2>
            </div>
            <p>We take our cues from the best teams in sport: bring your strengths, trust your crew and celebrate the progress we make together.</p>
          </div>
          <div className="wt-team-principles">
            {principles.map((principle, index) => {
              const Icon = principle.icon;
              return (
                <article className="wt-team-principle wt-team-reveal" key={principle.number} style={{ transitionDelay: `${index * 90}ms` }}>
                  <div className="wt-team-principle-top"><span>{principle.number}</span><Icon size={20} strokeWidth={1.6} aria-hidden="true" /></div>
                  <h3>{principle.title}</h3>
                  <p>{principle.description}</p>
                  <div className="wt-team-principle-line" />
                </article>
              );
            })}
          </div>
        </section>

        <section className="wt-team-cta" aria-labelledby="team-cta-heading">
          <div className="wt-team-cta-inner wt-team-reveal">
            <div className="wt-team-cta-mark"><Plane size={23} aria-hidden="true" /></div>
            <span className="wt-team-eyebrow"><span className="wt-team-live-dot" /> SAME MISSION. EVERY SHIFT.</span>
            <h2 id="team-cta-heading">Different strengths.<br /><em>One unstoppable crew.</em></h2>
            <p>Bring your heart, your hustle and your whole self. There’s a place for you in this crew—and someone counting on what only you can do.</p>
            <a className="wt-team-button wt-team-button-primary" href="/internal">
              <ShieldCheck size={16} aria-hidden="true" /> Access the internal portal <ArrowRight size={17} aria-hidden="true" />
            </a>
          </div>
          <div className="wt-team-cta-caption"><span>PRECISION · PACE · PEOPLE</span><span>WINGED TYCOONS / INTERNAL</span></div>
        </section>
      </main>

      <footer className="wt-team-footer">
        <a className="wt-team-brand" href="#top" aria-label="Winged Tycoons team portal home">
          <img src="/branding/WingedTycoons.png" alt="" width="48" height="37" />
          <span className="wt-team-brand-copy"><strong>WINGED TYCOONS</strong><span>AVIATION, IN MOTION</span></span>
        </a>
        <span>All heart. All in. All one team.</span>
        <a href="/internal">Internal portal access <ArrowUpRight size={14} aria-hidden="true" /></a>
      </footer>
    </div>
  );
};
