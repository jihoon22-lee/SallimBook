import { Link } from "react-router";
import { Icon } from "./Icon";
import type { ScreenLink } from "./screens";

export function RelatedLinks({ links }: { links: ScreenLink[] }) {
  return (
    <ul className="related-links">
      {links.map((link) => (
        <li key={link.to}>
          <Link to={link.to}>
            <span>
              <strong>{link.label}</strong>
              {link.description && <small>{link.description}</small>}
            </span>
            <Icon name="arrow-up-right" size={18} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
